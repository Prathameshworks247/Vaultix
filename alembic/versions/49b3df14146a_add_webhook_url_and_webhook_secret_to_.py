"""add webhook_url and webhook_secret to merchants

Revision ID: 49b3df14146a
Revises: e2b5d12659ae
Create Date: 2026-09-10 17:48:42.018875

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '49b3df14146a'
down_revision: Union[str, Sequence[str], None] = 'e2b5d12659ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # celery_taskmeta/celery_tasksetmeta are managed by Celery's DB result backend, not by
    # our models - autogenerate flags them as "removed" since they aren't declared here, but
    # dropping them would break the result backend, so they're deliberately left alone.
    op.add_column('merchants', sa.Column('webhook_url', sa.String(), nullable=True))
    op.add_column('merchants', sa.Column('webhook_secret', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('merchants', 'webhook_secret')
    op.drop_column('merchants', 'webhook_url')
