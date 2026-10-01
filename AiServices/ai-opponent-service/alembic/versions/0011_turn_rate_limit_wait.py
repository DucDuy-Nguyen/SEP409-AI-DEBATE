"""opponent_turns.rate_limit_wait_ms: tong thoi gian cho 429 cua luot

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-30

Dev log muc 2.12: cho 429 cua luot noi gio chi bi gioi han boi TURN_TOTAL_BUDGET_SECONDS -> ghi tong thoi gian cho
cua moi luot (tung lan cho van o opponent_llm_calls.rate_limit_wait_ms).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opponent_turns', sa.Column('rate_limit_wait_ms', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('opponent_turns', 'rate_limit_wait_ms')
