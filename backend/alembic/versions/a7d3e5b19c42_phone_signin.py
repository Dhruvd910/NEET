"""phone sign-in (Tekurious): phone, tekurious user id, optional email

Revision ID: a7d3e5b19c42
Revises: 8c41f0a2d9e3
Create Date: 2026-11-02 16:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d3e5b19c42'
down_revision: Union[str, Sequence[str], None] = '8c41f0a2d9e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('email', existing_type=sa.String(length=254), nullable=True)
        batch_op.add_column(sa.Column('phone', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('tekurious_user_id', sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f('ix_users_phone'), ['phone'], unique=True)
        batch_op.create_index(batch_op.f('ix_users_tekurious_user_id'), ['tekurious_user_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_tekurious_user_id'))
        batch_op.drop_index(batch_op.f('ix_users_phone'))
        batch_op.drop_column('tekurious_user_id')
        batch_op.drop_column('phone')
        batch_op.alter_column('email', existing_type=sa.String(length=254), nullable=False)
