"""P16.3: indexes for the log retention purges (SRS 15).

ai_tool_log had no index at all, and sync_errors none on created_at, which is the only column
the purge filters on. sync_runs already has (company_id, started_at).

Written from app.models and checked with `alembic check`.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-06 15:20:00.000000
"""

from alembic import op


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(op.f("ix_ai_tool_log_created_at"), "ai_tool_log", ["created_at"], unique=False)
    op.create_index(op.f("ix_sync_errors_created_at"), "sync_errors", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sync_errors_created_at"), table_name="sync_errors")
    op.drop_index(op.f("ix_ai_tool_log_created_at"), table_name="ai_tool_log")
