"""giai doan 3b: opponent_turns.ai_points, opponent_llm_calls.speech_checks

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-30

ai_points: dan y cua luot AI (turn_full_v1) — ledger "nhung dieu ban DA khang dinh" dung lai o cac luot sau.
speech_checks: kiem tra bai noi CHI LOG (so khong nam trong "Giả sử", xung "em").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opponent_turns', sa.Column('ai_points', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('opponent_llm_calls', sa.Column('speech_checks', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('opponent_llm_calls', 'speech_checks')
    op.drop_column('opponent_turns', 'ai_points')
