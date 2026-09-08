import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User, UserSession
from app.routers.auth import COOKIE, verify_password


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)
        def database():
            with self.session() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.credentials = {'username': 'Test_User', 'password': 'safe-password123'}

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def register(self):
        return self.client.post('/api/auth/register', json=self.credentials)

    def test_full_lifecycle(self):
        self.assertEqual(self.client.get('/', follow_redirects=False).status_code, 303)
        for path in ['/api/routes/', '/api/prices/latest', '/api/ai/price-trends', '/api/auth/me']:
            self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post('/api/ai/search', json={'query':'test'}).status_code, 401)
        response = self.register()
        self.assertEqual(response.status_code, 201)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        token = self.client.cookies.get(COOKIE)
        with self.session() as db:
            user = db.query(User).one()
            self.assertNotEqual(user.password_hash, self.credentials['password'])
            self.assertTrue(verify_password(self.credentials['password'], user.password_hash))
            self.assertNotEqual(db.query(UserSession).one().token_hash, token)
        self.assertEqual(self.client.get('/api/auth/me').json()['username'], 'test_user')
        for path in ['/', '/dashboard', '/api/routes/']:
            self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.client.cookies.set(COOKIE, token)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.client.cookies.clear()
        self.assertEqual(self.client.post('/api/auth/login', json=self.credentials).status_code, 200)

    def test_invalid_credentials_expiry_and_cross_site(self):
        self.assertEqual(self.register().status_code, 201)
        bad = {**self.credentials, 'password': 'wrong-password'}
        self.assertEqual(self.client.post('/api/auth/login', json=bad).status_code, 401)
        self.assertEqual(self.client.post('/api/auth/register', json={**bad, 'username':'!'}).status_code, 422)
        self.assertEqual(self.client.post('/api/auth/logout', headers={'Origin':'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/routes/', json={}, headers={'Origin':'https://evil.example'}).status_code, 403)
        with self.session() as db:
            db.query(UserSession).update({'expires_at': datetime.utcnow() - timedelta(seconds=1)})
            db.commit()
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE, 'forged-token')
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_login_rotates_session(self):
        self.register()
        previous = self.client.cookies.get(COOKIE)
        self.client.post('/api/auth/login', json=self.credentials)
        self.assertNotEqual(self.client.cookies.get(COOKIE), previous)
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE, previous)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)


class MigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade(self):
        import importlib.util
        from pathlib import Path
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import inspect

        path = Path(__file__).resolve().parents[1] / 'migrations/versions/20260908_03_user_login.py'
        spec = importlib.util.spec_from_file_location('auth_migration', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            self.assertEqual(set(inspect(connection).get_table_names()), {'users', 'user_sessions'})
            self.assertEqual(inspect(connection).get_unique_constraints('users')[0]['column_names'], ['username'])
            migration.downgrade()
            self.assertEqual(inspect(connection).get_table_names(), [])
        engine.dispose()

    def test_initial_account_is_seeded_without_overwriting(self):
        import importlib.util
        from pathlib import Path
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy import select, update

        path = Path(__file__).resolve().parents[1] / 'migrations/versions/20260908_04_initial_account.py'
        spec = importlib.util.spec_from_file_location('seed_migration', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine('sqlite://')
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            row = connection.execute(select(User.__table__)).mappings().one()
            self.assertEqual(row['username'], 'admin')
            self.assertEqual(row['password_hash'], migration.INITIAL_PASSWORD_HASH)
            connection.execute(update(User).values(password_hash='existing-password-hash'))
            migration.upgrade()
            migration.downgrade()
            rows = connection.execute(select(User.__table__)).mappings().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['password_hash'], 'existing-password-hash')
        engine.dispose()
