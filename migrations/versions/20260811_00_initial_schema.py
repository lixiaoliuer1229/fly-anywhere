"""Create the original route and price tables.

Revision ID: 20260811_00
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "20260811_00"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("departure_city", sa.String(50), nullable=False, comment="出发城市"),
        sa.Column("arrival_city", sa.String(50), nullable=False, comment="到达城市"),
        sa.Column("airline", sa.String(100), nullable=True, server_default="", comment="航空公司"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "prices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("route_id", sa.Integer(), sa.ForeignKey("routes.id"), nullable=False),
        sa.Column("price", sa.Float(), nullable=False, comment="价格(元)"),
        sa.Column("cabin_class", sa.String(20), nullable=True, server_default="economy", comment="舱位"),
        sa.Column("source", sa.String(20), nullable=False, comment="数据来源"),
        sa.Column("scraped_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("prices")
    op.drop_table("routes")
