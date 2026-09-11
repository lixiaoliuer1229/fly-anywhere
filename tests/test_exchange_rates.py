import unittest
from unittest.mock import patch, Mock
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ExchangeRate
from app.services.exchange_rates import fetch_exchange_rate
from app.services.scheduler import run_exchange_rate_fetch


class ExchangeRateTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        def database():
            yield self.db
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app)
        self.response = Mock()
        self.response.json.return_value = dict(base='CNY', quote='JPY', rate=20, date='2026-09-10')
        self.http = patch('app.services.exchange_rates.httpx.Client')
        self.http.start().return_value.__enter__.return_value.get.return_value = self.response

    def tearDown(self):
        self.http.stop()
        self.client.close()
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def login(self):
        self.client.post('/api/auth/register', json={'username':'fx_test', 'password':'safe-password123'})

    def test_auth_empty_fetch_history_and_inverse(self):
        self.assertEqual(self.client.get('/api/exchange-rates').status_code, 401)
        self.assertEqual(self.client.post('/api/exchange-rates/fetch').status_code, 401)
        self.login()
        self.assertIsNone(self.client.get('/api/exchange-rates').json()['latest'])
        self.assertEqual(self.client.post('/api/exchange-rates/fetch').json()['cny_per_100_jpy'], 5)
        result = self.client.get('/api/exchange-rates').json()
        self.assertEqual(len(result['points']), 1)
        self.assertEqual(result['latest']['rate_date'], '2026-09-10')
        self.assertEqual(self.client.get('/api/exchange-rates?limit=0').status_code, 422)
        self.assertEqual(self.client.post('/api/exchange-rates/fetch', headers={'Origin':'https://evil.example'}).status_code, 403)

    def test_duplicate_date_updates_and_history_order(self):
        fetch_exchange_rate(self.db)
        self.response.json.return_value['rate'] = 21
        fetch_exchange_rate(self.db)
        self.assertEqual(self.db.query(ExchangeRate).count(), 1)
        self.assertEqual(self.db.query(ExchangeRate).one().rate, Decimal(21))
        self.response.json.return_value['date'] = '2026-09-09'
        fetch_exchange_rate(self.db)
        self.login()
        result = self.client.get('/api/exchange-rates').json()
        self.assertEqual(result['latest']['rate_date'], '2026-09-10')
        self.assertEqual(result['points'][0]['rate_date'], '2026-09-09')

    def test_invalid_and_failed_responses_preserve_history(self):
        fetch_exchange_rate(self.db)
        for rate in [0, -1, 'NaN', 'Infinity', 'bad']:
            self.response.json.return_value['rate'] = rate
            with self.assertRaises(ValueError):
                fetch_exchange_rate(self.db)
        self.login()
        self.response.raise_for_status.side_effect = RuntimeError('unavailable')
        with self.assertLogs('app.routers.exchange_rates', level='ERROR'):
            self.assertEqual(self.client.post('/api/exchange-rates/fetch').status_code, 502)
        self.assertEqual(self.db.query(ExchangeRate).count(), 1)

    def test_schedule_fetches_without_routes(self):
        with patch('app.services.scheduler.SessionLocal', self.sessions):
            run_exchange_rate_fetch()
        self.assertEqual(self.db.query(ExchangeRate).count(), 1)
