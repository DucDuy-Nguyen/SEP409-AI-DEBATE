"""opponent_llm_calls: reasoning_tokens, finish_reason, reasoning_effort

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-30

Dev log muc 2.10: tran 15:11 co output RONG (Groq 400 json_validate_failed, failed_generation "") va tokens_out
3274/4000 — can tach token suy luan va ly do dung de biet output bi cat vi het max_tokens.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opponent_llm_calls', sa.Column('reasoning_tokens', sa.Integer(), nullable=True))
    op.add_column('opponent_llm_calls', sa.Column('finish_reason', sa.String(length=30), nullable=True))
    op.add_column('opponent_llm_calls', sa.Column('reasoning_effort', sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column('opponent_llm_calls', 'reasoning_effort')
    op.drop_column('opponent_llm_calls', 'finish_reason')
    op.drop_column('opponent_llm_calls', 'reasoning_tokens')
