"""Single-use initial password (D-052): users.must_change_password. Existing accounts get false;
only accounts an Owner creates from now on start with it set.

Written from app.models and checked with `alembic check` (2026-10-02).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-02 00:01:26.582495
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
