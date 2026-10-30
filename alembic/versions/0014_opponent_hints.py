"""goi y phan bac (WF-02): opponent_hints, opponent_llm_calls.hint_id; llm_call_purpose += 'hint'

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-30

POST /opponent/sessions/{external_session_id}/hints. Idempotent theo (session_id, request_id). Loi goi LLM cua hint log
vao opponent_llm_calls (purpose='hint' + stance_review cua hint), hint_id tro toi hint da luu (NULL neu that bai).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0014'
down_revision: Union[str, None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PG >= 12 cho phep ADD VALUE trong transaction (chi khong duoc dung gia tri moi trong cung transaction).
    op.execute("ALTER TYPE llm_call_purpose ADD VALUE IF NOT EXISTS 'hint'")
    op.create_table(
        'opponent_hints',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('session_id', sa.UUID(), nullable=False),
        sa.Column('request_id', sa.String(length=200), nullable=False),
        sa.Column('learner_turn_index', sa.Integer(), nullable=False),
        sa.Column('target_turn_index', sa.Integer(), nullable=False),
        sa.Column('learner_draft', sa.Text(), nullable=True),
        sa.Column('strategies', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('prompt_version', sa.String(length=50), nullable=False),
        sa.Column('llm_provider', sa.String(length=50), nullable=False),
        sa.Column('llm_model', sa.String(length=100), nullable=False),
        sa.Column('temperature', sa.Float(), nullable=False),
        sa.Column('tokens_in', sa.Integer(), nullable=True),
        sa.Column('tokens_out', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
        sa.CheckConstraint('learner_turn_index BETWEEN 1 AND 6', name='ck_opponent_hints_learner_turn_index'),
        sa.CheckConstraint('target_turn_index BETWEEN 1 AND 6', name='ck_opponent_hints_target_turn_index'),
        sa.ForeignKeyConstraint(['session_id'], ['opponent_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'request_id', name='uq_opponent_hints_session_request'),
    )
    op.create_index('ix_opponent_hints_session_id', 'opponent_hints', ['session_id'])
    op.add_column('opponent_llm_calls', sa.Column('hint_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_opponent_llm_calls_hint_id', 'opponent_llm_calls', 'opponent_hints', ['hint_id'], ['id'], ondelete='CASCADE'
    )
    op.create_index('ix_opponent_llm_calls_hint_id', 'opponent_llm_calls', ['hint_id'])


def downgrade() -> None:
    op.drop_index('ix_opponent_llm_calls_hint_id', table_name='opponent_llm_calls')
    op.drop_constraint('fk_opponent_llm_calls_hint_id', 'opponent_llm_calls', type_='foreignkey')
    op.drop_column('opponent_llm_calls', 'hint_id')
    op.drop_index('ix_opponent_hints_session_id', table_name='opponent_hints')
    op.drop_table('opponent_hints')
    # Postgres khong co "DROP VALUE" cho enum -> xoa du lieu dung gia tri do, dung lai type khong co no.
    op.execute("DELETE FROM opponent_llm_calls WHERE purpose = 'hint'")
    op.execute("ALTER TYPE llm_call_purpose RENAME TO llm_call_purpose_old")
    op.execute("CREATE TYPE llm_call_purpose AS ENUM ('case_plan', 'stance_review', 'turn')")
    op.execute(
        "ALTER TABLE opponent_llm_calls ALTER COLUMN purpose TYPE llm_call_purpose "
        "USING purpose::text::llm_call_purpose"
    )
    op.execute("DROP TYPE llm_call_purpose_old")
