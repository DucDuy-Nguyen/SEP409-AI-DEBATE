"""opponent_sessions: motion_type (enum, nullable), motion_reading_provided (text, nullable)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-30

Thi nghiem motion_type (dev log muc 2.13): Main Flow co the gui kem loai kien nghi + cach hieu da duyet. Ca hai
NULL = hanh vi cu (case_plan_v5).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0012'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

motion_type = postgresql.ENUM('policy', 'comparative', 'value', name='motion_type')


def upgrade() -> None:
    motion_type.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'opponent_sessions',
        sa.Column('motion_type', postgresql.ENUM(name='motion_type', create_type=False), nullable=True),
    )
    op.add_column('opponent_sessions', sa.Column('motion_reading_provided', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('opponent_sessions', 'motion_reading_provided')
    op.drop_column('opponent_sessions', 'motion_type')
    motion_type.drop(op.get_bind(), checkfirst=True)
