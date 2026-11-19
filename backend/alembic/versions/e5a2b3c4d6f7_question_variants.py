"""new versions of bank questions: which question a version was made from

Revision ID: e5a2b3c4d6f7
Revises: d4f1a2b3c5e6
Create Date: 2026-11-04 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5a2b3c4d6f7'
down_revision: Union[str, Sequence[str], None] = 'd4f1a2b3c5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('variant_of', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_questions_variant_of'), ['variant_of'], unique=False)
        batch_op.create_foreign_key('fk_questions_variant_of', 'questions', ['variant_of'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_questions_variant_of', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_questions_variant_of'))
        batch_op.drop_column('variant_of')
