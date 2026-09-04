"""Expand flight number for multi-segment itineraries.

Revision ID: 20260904_02
Revises: 20260812_01
"""
from alembic import op
import sqlalchemy as sa


revision = "20260904_02"
down_revision = "20260812_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "flight_offers",
        "flight_number",
        existing_type=sa.String(length=30),
        type_=sa.String(length=120),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "flight_offers",
        "flight_number",
        existing_type=sa.String(length=120),
        type_=sa.String(length=30),
        existing_nullable=True,
    )
