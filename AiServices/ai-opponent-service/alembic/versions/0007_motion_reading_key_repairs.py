"""case file JSONB: motion_interpretation -> motion_reading; opponent_llm_calls.key_repairs

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29

Doi ten truong vi gpt-oss-120b lap lai loi go "motion_interinterpretation" (dev log muc 2.4j). Chi doi key trong
opponent_case_files.content; raw_output / vague_evidence cu trong opponent_llm_calls giu nguyen (lich su).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _rename_top_level_key(old: str, new: str) -> None:
    op.execute(
        f"""
        UPDATE opponent_case_files
        SET content = (content - '{old}') || jsonb_build_object('{new}', content -> '{old}')
        WHERE content ? '{old}' AND NOT content ? '{new}'
        """
    )


def upgrade() -> None:
    _rename_top_level_key('motion_interpretation', 'motion_reading')
    op.add_column(
        'opponent_llm_calls',
        sa.Column('key_repairs', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('opponent_llm_calls', 'key_repairs')
    _rename_top_level_key('motion_reading', 'motion_interpretation')
