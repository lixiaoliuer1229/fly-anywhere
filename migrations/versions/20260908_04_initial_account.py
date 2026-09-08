"""Create the initial admin account without overwriting existing credentials."""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "20260908_04"
down_revision = "20260908_03"
branch_labels = None
depends_on = None

INITIAL_PASSWORD_HASH = 'scrypt$1c5da12435fe96c899979508e13b81c8$6a5af7dde0d12be6c34b02c8b749d9b8f9e4ab6998dc772efdba19dad8e473632be0fc697fa509647b4a622984df92daa59bf0f1b119906a742133503d74d2b5'


def upgrade():
    users = sa.table("users",
        sa.column("username", sa.String(64)),
        sa.column("password_hash", sa.String(255)),
        sa.column("created_at", sa.DateTime()))
    # INSERT ... SELECT also supports Alembic offline SQL generation.
    existing = sa.select(users.c.username).where(users.c.username == "admin").exists()
    op.execute(users.insert().from_select(
        ["username", "password_hash", "created_at"],
        sa.select(sa.literal("admin"), sa.literal(INITIAL_PASSWORD_HASH),
                  sa.literal(datetime.utcnow())).where(~existing)))


def downgrade():
    # Keep the account: rolling back a seed must not remove a user's login.
    pass
