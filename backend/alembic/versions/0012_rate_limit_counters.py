"""P16.11: rate_limit_counters - one request count per key per window, shared by all replicas.

The in-process counters let N replicas allow N x the limit (SEC-1.9, D-033 #3), so production
could not run more than one backend. `window_start` is wall-clock, so every replica agrees on
which window a request falls in.

Written from app.models and checked with `alembic check`.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-06 14:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_counters",
        sa.Column("bucket_key", sa.Text(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("bucket_key", "window_start", name=op.f("pk_rate_limit_counters")),
    )
    # The purge deletes whole finished windows, so it leads with window_start.
    op.create_index(
        op.f("ix_rate_limit_counters_window_start"),
        "rate_limit_counters",
        ["window_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_rate_limit_counters_window_start"), table_name="rate_limit_counters")
    op.drop_table("rate_limit_counters")
