"""opponent_sessions: external_session_id + learner_side; opponent_case_files: 1 case file / session

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-25

Du lieu cu (neu co):
- external_session_id backfill = id noi bo (dang text) — chi de thoa NOT NULL/UNIQUE.
- learner_side backfill = phia doi dien ai_side.
- Case file trung session: GIU ban moi nhat, xoa ban cu truoc khi them UNIQUE.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- opponent_sessions ---
    op.add_column('opponent_sessions', sa.Column('external_session_id', sa.Text(), nullable=True))
    op.add_column(
        'opponent_sessions',
        sa.Column('learner_side', postgresql.ENUM('pro', 'con', name='debate_side', create_type=False), nullable=True),
    )
    op.execute("UPDATE opponent_sessions SET external_session_id = id::text WHERE external_session_id IS NULL")
    op.execute(
        "UPDATE opponent_sessions SET learner_side = "
        "CASE ai_side WHEN 'pro' THEN 'con'::debate_side ELSE 'pro'::debate_side END "
        "WHERE learner_side IS NULL"
    )
    op.alter_column('opponent_sessions', 'external_session_id', nullable=False)
    op.alter_column('opponent_sessions', 'learner_side', nullable=False)
    op.create_unique_constraint(
        'uq_opponent_sessions_external_session_id', 'opponent_sessions', ['external_session_id']
    )
    op.create_check_constraint('ck_opponent_sessions_sides_differ', 'opponent_sessions', 'learner_side <> ai_side')

    # --- opponent_case_files: dung 1 case file / session ---
    op.execute(
        "DELETE FROM opponent_case_files cf USING opponent_case_files newer "
        "WHERE cf.session_id = newer.session_id AND (cf.created_at, cf.id) < (newer.created_at, newer.id)"
    )
    # UNIQUE tu tao index tren session_id -> index thuong cu thanh thua.
    op.drop_index('ix_opponent_case_files_session_id', table_name='opponent_case_files')
    op.create_unique_constraint('uq_opponent_case_files_session_id', 'opponent_case_files', ['session_id'])


def downgrade() -> None:
    op.drop_constraint('uq_opponent_case_files_session_id', 'opponent_case_files', type_='unique')
    op.create_index('ix_opponent_case_files_session_id', 'opponent_case_files', ['session_id'], unique=False)

    op.drop_constraint('ck_opponent_sessions_sides_differ', 'opponent_sessions', type_='check')
    op.drop_constraint('uq_opponent_sessions_external_session_id', 'opponent_sessions', type_='unique')
    op.drop_column('opponent_sessions', 'learner_side')  # giu enum debate_side — ai_side van dung
    op.drop_column('opponent_sessions', 'external_session_id')
