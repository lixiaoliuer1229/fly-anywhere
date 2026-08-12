"""Add AI search monitoring tables and route criteria.

Revision ID: 20260812_01
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "20260812_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("routes") as batch:
        batch.add_column(sa.Column("departure_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("return_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("trip_type", sa.String(20), nullable=False, server_default="one_way"))
        batch.add_column(sa.Column("adults", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("cabin_class", sa.String(20), nullable=False, server_default="economy"))
        batch.add_column(sa.Column("target_price", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"))
        batch.add_column(sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.create_table(
        "search_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("route_id", sa.Integer(), sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("warning", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(30), nullable=False, server_default="tavily"),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_search_runs_route_id", "search_runs", ["route_id"])
    op.create_index("ix_search_runs_status", "search_runs", ["status"])

    op.create_table(
        "flight_offers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("search_run_id", sa.Integer(), sa.ForeignKey("search_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("airline", sa.String(100), nullable=False, server_default="未知"),
        sa.Column("flight_number", sa.String(30), nullable=True),
        sa.Column("departure", sa.String(100), nullable=False),
        sa.Column("arrival", sa.String(100), nullable=False),
        sa.Column("departure_time", sa.String(80), nullable=True),
        sa.Column("arrival_time", sa.String(80), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("cabin_class", sa.String(30), nullable=False, server_default="economy"),
        sa.Column("source_title", sa.String(255), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("is_starting_price", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_flight_offers_search_run_id", "flight_offers", ["search_run_id"])

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("route_id", sa.Integer(), sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("search_run_id", sa.Integer(), sa.ForeignKey("search_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel_type", sa.String(30), nullable=False, server_default="wecom_webhook"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("message_content", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notification_deliveries_route_id", "notification_deliveries", ["route_id"])
    op.create_index("ix_notification_deliveries_search_run_id", "notification_deliveries", ["search_run_id"])
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("flight_offers")
    op.drop_table("search_runs")
    with op.batch_alter_table("routes") as batch:
        for column in (
            "updated_at", "enabled", "currency", "target_price", "cabin_class",
            "adults", "trip_type", "return_date", "departure_date",
        ):
            batch.drop_column(column)
