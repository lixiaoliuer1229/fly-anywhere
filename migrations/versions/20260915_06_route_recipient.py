"""Allow a monitored route to have an exclusive report recipient."""
from alembic import op
import sqlalchemy as sa

revision = "20260915_06"
down_revision = "20260911_05"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("routes", sa.Column("report_recipient", sa.String(254), nullable=True))


def downgrade():
    op.drop_column("routes", "report_recipient")
