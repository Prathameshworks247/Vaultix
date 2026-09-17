"""add merchant api_key, dead_letters table, scope idempotency key to merchant

Revision ID: a7767d40fe44
Revises: 49b3df14146a
Create Date: 2026-09-17 19:03:36.683830

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7767d40fe44'
down_revision: Union[str, Sequence[str], None] = '49b3df14146a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # celery_taskmeta/celery_tasksetmeta are managed by Celery's DB result backend, not by
    # our models - autogenerate flags them as "removed" since they aren't declared here, but
    # dropping them would break the result backend, so they're deliberately left alone.
    op.create_table('dead_letters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('task_name', sa.String(), nullable=False),
        sa.Column('task_id', sa.String(), nullable=False),
        sa.Column('args', sa.JSON(), nullable=True),
        sa.Column('exception', sa.String(), nullable=False),
        sa.Column('traceback', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.add_column('merchants', sa.Column('api_key', sa.String(), nullable=True))
    op.create_index(op.f('ix_merchants_api_key'), 'merchants', ['api_key'], unique=True)

    # idempotency_key moves from a bare global-unique column to unique-per-merchant, so two
    # different merchants picking the same key string can't collide or leak each other's payment.
    op.drop_index(op.f('ix_payments_idempotency_key'), table_name='payments')
    op.create_index(op.f('ix_payments_idempotency_key'), 'payments', ['idempotency_key'], unique=False)
    op.create_unique_constraint('uq_merchant_idempotency_key', 'payments', ['merchant_id', 'idempotency_key'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_merchant_idempotency_key', 'payments', type_='unique')
    op.drop_index(op.f('ix_payments_idempotency_key'), table_name='payments')
    op.create_index(op.f('ix_payments_idempotency_key'), 'payments', ['idempotency_key'], unique=True)
    op.drop_index(op.f('ix_merchants_api_key'), table_name='merchants')
    op.drop_column('merchants', 'api_key')
    op.drop_table('dead_letters')
