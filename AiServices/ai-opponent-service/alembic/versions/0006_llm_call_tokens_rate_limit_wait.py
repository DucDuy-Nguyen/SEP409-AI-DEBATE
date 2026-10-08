"""opponent_llm_calls: tokens_in, tokens_out, rate_limit_wait_ms

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26

tokens_* lay tu usage provider tra ve (do nang luc phuc vu voi TPM free tier); rate_limit_wait_ms = thoi gian
DA CHO sau dong 429 nay (theo retry-after / "try again in Xs" + jitter).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opponent_llm_calls', sa.Column('tokens_in', sa.Integer(), nullable=True))
    op.add_column('opponent_llm_calls', sa.Column('tokens_out', sa.Integer(), nullable=True))
    op.add_column('opponent_llm_calls', sa.Column('rate_limit_wait_ms', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('opponent_llm_calls', 'rate_limit_wait_ms')
    op.drop_column('opponent_llm_calls', 'tokens_out')
    op.drop_column('opponent_llm_calls', 'tokens_in')
