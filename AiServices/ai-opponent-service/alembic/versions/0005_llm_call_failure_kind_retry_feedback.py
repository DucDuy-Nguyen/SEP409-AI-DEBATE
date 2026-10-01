"""opponent_llm_calls: failure_kind + retry_feedback (retry co phan hoi)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opponent_llm_calls', sa.Column('failure_kind', sa.String(length=30), nullable=True))
    op.add_column('opponent_llm_calls', sa.Column('retry_feedback', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('opponent_llm_calls', 'retry_feedback')
    op.drop_column('opponent_llm_calls', 'failure_kind')
