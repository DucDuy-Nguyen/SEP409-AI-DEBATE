"""giai doan 3a: opponent_speeches, opponent_turns, opponent_llm_calls.turn_id; llm_call_purpose += 'turn'

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29

Format tran 6 luot (app/opponent/match_format.py). opponent_speeches luu snapshot MOI bai noi (learner + AI);
opponent_turns luu cach sinh bai noi cua AI. Loi goi LLM sinh bai noi log vao opponent_llm_calls (purpose='turn',
turn_id tro toi luot da luu; NULL neu luot sinh that bai).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

debate_round_type = postgresql.ENUM('opening', 'rebuttal', 'closing', name='debate_round_type')
speech_speaker = postgresql.ENUM('learner', 'ai', name='speech_speaker')
turn_mode = postgresql.ENUM('opening_first', 'opening_reply', 'rebuttal', 'closing', name='turn_mode')


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _uuid_pk() -> sa.Column:
    return sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False)


def _created_at() -> sa.Column:
    return sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False)


def upgrade() -> None:
    # PG >= 12 cho phep ADD VALUE trong transaction (chi khong duoc dung gia tri moi trong cung transaction).
    op.execute("ALTER TYPE llm_call_purpose ADD VALUE IF NOT EXISTS 'turn'")
    bind = op.get_bind()
    for enum in (debate_round_type, speech_speaker, turn_mode):
        enum.create(bind, checkfirst=True)

    op.create_table(
        'opponent_speeches',
        _uuid_pk(),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('turn_index', sa.Integer(), nullable=False),
        sa.Column('round_type', _enum('debate_round_type'), nullable=False),
        sa.Column('speaker', _enum('speech_speaker'), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        _created_at(),
        sa.CheckConstraint('turn_index BETWEEN 1 AND 6', name='ck_opponent_speeches_turn_index'),
        sa.ForeignKeyConstraint(['session_id'], ['opponent_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'turn_index', name='uq_opponent_speeches_session_turn'),
    )
    op.create_index('ix_opponent_speeches_session_id', 'opponent_speeches', ['session_id'])

    op.create_table(
        'opponent_turns',
        _uuid_pk(),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('speech_id', sa.UUID(), nullable=False),
        sa.Column('turn_index', sa.Integer(), nullable=False),
        sa.Column('round_type', _enum('debate_round_type'), nullable=False),
        sa.Column('mode', _enum('turn_mode'), nullable=False),
        sa.Column('generator_version', sa.String(length=50), nullable=False),
        sa.Column('llm_provider', sa.String(length=50), nullable=False),
        sa.Column('llm_model', sa.String(length=100), nullable=False),
        sa.Column('temperature', sa.Float(), nullable=False),
        sa.Column('learner_claims', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('premises', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('target_premise', sa.Text(), nullable=True),
        sa.Column('word_count', sa.Integer(), nullable=False),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('tokens_in', sa.Integer(), nullable=True),
        sa.Column('tokens_out', sa.Integer(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(['session_id'], ['opponent_sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['speech_id'], ['opponent_speeches.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'turn_index', name='uq_opponent_turns_session_turn'),
    )
    op.create_index('ix_opponent_turns_session_id', 'opponent_turns', ['session_id'])

    op.add_column('opponent_llm_calls', sa.Column('turn_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_opponent_llm_calls_turn_id', 'opponent_llm_calls', 'opponent_turns', ['turn_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index('ix_opponent_llm_calls_turn_id', 'opponent_llm_calls', ['turn_id'])


def downgrade() -> None:
    op.drop_index('ix_opponent_llm_calls_turn_id', table_name='opponent_llm_calls')
    op.drop_constraint('fk_opponent_llm_calls_turn_id', 'opponent_llm_calls', type_='foreignkey')
    op.drop_column('opponent_llm_calls', 'turn_id')
    op.drop_index('ix_opponent_turns_session_id', table_name='opponent_turns')
    op.drop_table('opponent_turns')
    op.drop_index('ix_opponent_speeches_session_id', table_name='opponent_speeches')
    op.drop_table('opponent_speeches')
    bind = op.get_bind()
    for enum in (turn_mode, speech_speaker, debate_round_type):
        enum.drop(bind, checkfirst=True)
    # Postgres khong co "DROP VALUE" cho enum -> xoa du lieu dung gia tri do, dung lai type khong co no.
    op.execute("DELETE FROM opponent_llm_calls WHERE purpose = 'turn'")
    op.execute("ALTER TYPE llm_call_purpose RENAME TO llm_call_purpose_old")
    op.execute("CREATE TYPE llm_call_purpose AS ENUM ('case_plan', 'stance_review')")
    op.execute(
        "ALTER TABLE opponent_llm_calls ALTER COLUMN purpose TYPE llm_call_purpose "
        "USING purpose::text::llm_call_purpose"
    )
    op.execute("DROP TYPE llm_call_purpose_old")
