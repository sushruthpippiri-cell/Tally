"""P15: anomaly detection. Checks `rule_triggered`, indexes `anomaly_flags` by company, adds the
columns behind D-055 #10/#11/#12, the rule job's cursor, and the read-only role's access.

The RLS policies are the part Alembic cannot see in the models (D-055 #5). Two are needed:
`tally_readonly` may read only the company fixed at spawn, so even a bug in the MCP server's own
query cannot return another company's evidence; and `tally_app` keeps full access, because
enabling RLS on a table applies it to every role except the owner, and without a policy the
application itself would see no rows at all.

Written from app.models and checked with `alembic check` (2026-10-05).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-05 12:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

RULES = ("UNUSUALLY_LARGE_SD", "UNUSUALLY_LARGE_MULTIPLE", "POSSIBLE_DUPLICATE")
REASONS = (
    "NOT_CONFIGURED",
    "CLAUDE_UNREACHABLE",
    "TIMEOUT",
    "REFUSED",
    "NUMBER_NOT_IN_EVIDENCE",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "anomaly_scan_state",
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("synced_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.company_id"], name=op.f("fk_anomaly_scan_state_company_id")
        ),
        sa.PrimaryKeyConstraint("company_id", name=op.f("pk_anomaly_scan_state")),
    )
    op.add_column(
        "anomaly_flags", sa.Column("explanation_unavailable_reason", sa.Text(), nullable=True)
    )
    op.add_column(
        "anomaly_flags",
        sa.Column(
            "explanation_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "anomaly_flags",
        sa.Column("explanation_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "anomaly_flags", sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint("rule_triggered", "anomaly_flags", _in("rule_triggered", RULES))
    op.create_check_constraint(
        "explanation_unavailable_reason",
        "anomaly_flags",
        _in("explanation_unavailable_reason", REASONS),
    )
    op.create_index(
        op.f("ix_anomaly_flags_company_id_flagged_at"),
        "anomaly_flags",
        ["company_id", "flagged_at"],
        unique=False,
    )

    # --- the read-only role's access (D-055 #5) ----------------------------------------------
    # The role is created by deploy/postgres/init/01-roles-and-databases.sh; skip quietly when
    # it is absent so a developer database made before P15 still migrates.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tally_readonly') THEN
            GRANT SELECT ON anomaly_flags TO tally_readonly;
          END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE anomaly_flags ENABLE ROW LEVEL SECURITY")
    # Without this the application itself would see no rows: enabling RLS applies to every role
    # except the table owner. The app enforces tenancy in its own queries (SEC-1.7).
    op.execute(
        "CREATE POLICY anomaly_flags_app ON anomaly_flags TO tally_app "
        "USING (true) WITH CHECK (true)"
    )
    # current_setting(..., true) is NULL when unset, so an unconfigured session sees nothing.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tally_readonly') THEN
            CREATE POLICY anomaly_flags_readonly ON anomaly_flags FOR SELECT TO tally_readonly
              USING (company_id = current_setting('app.company_id', true)::uuid);
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS anomaly_flags_readonly ON anomaly_flags")
    op.execute("DROP POLICY IF EXISTS anomaly_flags_app ON anomaly_flags")
    op.execute("ALTER TABLE anomaly_flags DISABLE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tally_readonly') THEN
            REVOKE SELECT ON anomaly_flags FROM tally_readonly;
          END IF;
        END $$;
        """
    )
    op.drop_index(op.f("ix_anomaly_flags_company_id_flagged_at"), table_name="anomaly_flags")
    op.drop_constraint("ck_anomaly_flags_explanation_unavailable_reason", "anomaly_flags")
    op.drop_constraint("ck_anomaly_flags_rule_triggered", "anomaly_flags")
    op.drop_column("anomaly_flags", "cleared_at")
    op.drop_column("anomaly_flags", "explanation_last_attempt_at")
    op.drop_column("anomaly_flags", "explanation_attempts")
    op.drop_column("anomaly_flags", "explanation_unavailable_reason")
    op.drop_table("anomaly_scan_state")
