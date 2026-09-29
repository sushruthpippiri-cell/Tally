"""Reconciliation runs: one summary row per compared run (P10, D-048 #8). It replaces
sync_runs.reconciled_at from 0007: the row's existence is what marks a run compared.

Written from app.models and checked with `alembic check` (2026-09-29).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29 13:10:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('reconciliation_runs',
    sa.Column('sync_run_id', sa.UUID(), nullable=False),
    sa.Column('company_id', sa.UUID(), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('as_of', sa.Date(), nullable=False),
    sa.Column('overall', sa.Text(), nullable=False),
    sa.Column('compared', sa.Integer(), nullable=False),
    sa.Column('failed', sa.Integer(), nullable=False),
    sa.Column('not_compared', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('unverified_gates', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("overall IN ('PASS', 'FAIL', 'INCOMPLETE')", name=op.f('ck_reconciliation_runs_overall')),
    sa.ForeignKeyConstraint(['company_id', 'sync_run_id'], ['sync_runs.company_id', 'sync_runs.sync_run_id'], name=op.f('fk_reconciliation_runs_company_id_sync_run_id')),
    sa.ForeignKeyConstraint(['company_id'], ['companies.company_id'], name=op.f('fk_reconciliation_runs_company_id')),
    sa.PrimaryKeyConstraint('sync_run_id', name=op.f('pk_reconciliation_runs'))
    )
    op.create_index(op.f('ix_reconciliation_runs_company_id_run_at'), 'reconciliation_runs', ['company_id', 'run_at'], unique=False)
    op.drop_column('sync_runs', 'reconciled_at')


def downgrade() -> None:
    op.add_column('sync_runs', sa.Column('reconciled_at', sa.DateTime(timezone=True), nullable=True))
    op.drop_index(op.f('ix_reconciliation_runs_company_id_run_at'), table_name='reconciliation_runs')
    op.drop_table('reconciliation_runs')
