"""opponent_sessions: burden_pro, burden_con (text, nullable) — thi nghiem case_plan_v6b

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-01

Dev log muc 2.15: "ganh nang chung minh" cua moi phe, Main Flow gui kem motion_type. NULL = hanh vi cu.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0013'
down_revision: Union[str, None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('opponent_sessions', sa.Column('burden_pro', sa.Text(), nullable=True))
    op.add_column('opponent_sessions', sa.Column('burden_con', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('opponent_sessions', 'burden_con')
    op.drop_column('opponent_sessions', 'burden_pro')
