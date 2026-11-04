"""opponent_turns: points_addressed (JSONB, nullable) — turn_full_v7

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-04

Dev log muc 3.2: cac muc premises.explicit cua bai MOI ma bai noi thuc su dap lai. NULL = luot sinh boi bo sinh khac /
khi tat do kho.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0015'
down_revision: Union[str, None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opponent_turns', sa.Column('points_addressed', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('opponent_turns', 'points_addressed')
