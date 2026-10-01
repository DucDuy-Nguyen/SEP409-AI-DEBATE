"""stance reviewer: llm_call_purpose += 'stance_review'; opponent_llm_calls.reviewer_verdict + reviewer_detail

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26

Cot reviewer_verdict / reviewer_detail la cot da du kien cho Phase 3 (reviewer tung luot noi),
lam som vi Stance Reviewer duoc dua len dung cho Case Planning.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

reviewer_verdict = postgresql.ENUM('pass', 'side_flip', 'unclear', name='reviewer_verdict')


def upgrade() -> None:
    # PG >= 12 cho phep ADD VALUE trong transaction (chi khong duoc dung gia tri moi trong cung transaction).
    op.execute("ALTER TYPE llm_call_purpose ADD VALUE IF NOT EXISTS 'stance_review'")
    reviewer_verdict.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'opponent_llm_calls',
        sa.Column('reviewer_verdict', postgresql.ENUM(name='reviewer_verdict', create_type=False), nullable=True),
    )
    op.add_column(
        'opponent_llm_calls',
        sa.Column('reviewer_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('opponent_llm_calls', 'reviewer_detail')
    op.drop_column('opponent_llm_calls', 'reviewer_verdict')
    reviewer_verdict.drop(op.get_bind(), checkfirst=True)
    # Postgres khong co "DROP VALUE" cho enum -> xoa du lieu dung gia tri do, dung lai type khong co no.
    op.execute("DELETE FROM opponent_llm_calls WHERE purpose = 'stance_review'")
    op.execute("ALTER TYPE llm_call_purpose RENAME TO llm_call_purpose_old")
    op.execute("CREATE TYPE llm_call_purpose AS ENUM ('case_plan')")
    op.execute(
        "ALTER TABLE opponent_llm_calls ALTER COLUMN purpose TYPE llm_call_purpose "
        "USING purpose::text::llm_call_purpose"
    )
    op.execute("DROP TYPE llm_call_purpose_old")
