"""previous-year NEET questions: the exam year a question appeared in

Revision ID: d4f1a2b3c5e6
Revises: a7d3e5b19c42
Create Date: 2026-11-03 19:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f1a2b3c5e6'
down_revision: Union[str, Sequence[str], None] = 'a7d3e5b19c42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('pyq_year', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_questions_pyq_year'), ['pyq_year'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_questions_pyq_year'))
        batch_op.drop_column('pyq_year')
