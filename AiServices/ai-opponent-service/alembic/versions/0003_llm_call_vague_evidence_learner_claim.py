"""opponent_llm_calls.vague_evidence (JSONB); case file JSONB: opponent_claim -> learner_claim

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26

Doi ten key trong du lieu cu de moi case file trong DB dung cung ten field voi CaseFile hien tai.
Khong dong vao "example" cu (khong bat dau bang "Giả sử"): GET debug tra JSON tho, khong validate lai.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rename_claim_key(old: str, new: str) -> None:
    # Doi ten key trong tung phan tu cua anticipated_opponent_arguments, giu nguyen thu tu.
    op.execute(
        f"""
        UPDATE opponent_case_files
        SET content = jsonb_set(
            content,
            '{{anticipated_opponent_arguments}}',
            (
                SELECT jsonb_agg(
                    CASE WHEN elem ? '{old}'
                         THEN (elem - '{old}') || jsonb_build_object('{new}', elem -> '{old}')
                         ELSE elem END
                    ORDER BY ord
                )
                FROM jsonb_array_elements(content -> 'anticipated_opponent_arguments')
                     WITH ORDINALITY AS t(elem, ord)
            )
        )
        WHERE jsonb_typeof(content -> 'anticipated_opponent_arguments') = 'array'
          AND jsonb_array_length(content -> 'anticipated_opponent_arguments') > 0
          AND content @? '$.anticipated_opponent_arguments[*].{old}'
        """
    )


def upgrade() -> None:
    op.add_column(
        'opponent_llm_calls',
        sa.Column('vague_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    _rename_claim_key('opponent_claim', 'learner_claim')


def downgrade() -> None:
    _rename_claim_key('learner_claim', 'opponent_claim')
    op.drop_column('opponent_llm_calls', 'vague_evidence')
