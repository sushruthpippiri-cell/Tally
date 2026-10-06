"""P15.5: anomaly_flags.party_ledger_id - which party the figures are about.

The rules already resolve the party ledger (and skip a voucher with more than one), so storing
it saves the list API and the evidence panel from joining the voucher's entries again - a join
that would have to re-apply the same ambiguity rule to get the same answer.

Written from app.models and checked with `alembic check` (2026-10-05).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-05 17:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("anomaly_flags", sa.Column("party_ledger_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_anomaly_flags_company_id_party_ledger_id"),
        "anomaly_flags",
        "ledgers",
        ["company_id", "party_ledger_id"],
        ["company_id", "ledger_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_anomaly_flags_company_id_party_ledger_id"), "anomaly_flags", type_="foreignkey"
    )
    op.drop_column("anomaly_flags", "party_ledger_id")
