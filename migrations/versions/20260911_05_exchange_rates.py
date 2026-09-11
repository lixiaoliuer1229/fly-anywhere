"""Store daily currency reference rates."""
from alembic import op
import sqlalchemy as sa

revision = "20260911_05"
down_revision = "20260908_04"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("exchange_rates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("base", sa.String(3), nullable=False),
        sa.Column("quote", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("base", "quote", "rate_date", name="uq_exchange_rate_pair_date"))


def downgrade():
    op.drop_table("exchange_rates")
