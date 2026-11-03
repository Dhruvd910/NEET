"""google sign-in and login events

Revision ID: 8c41f0a2d9e3
Revises: 5b2d9e41c7a0
Create Date: 2026-11-02 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8c41f0a2d9e3'
down_revision: Union[str, Sequence[str], None] = '5b2d9e41c7a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('google_sub', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('name', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('login_count', sa.Integer(), server_default='0', nullable=False))
        batch_op.create_index(batch_op.f('ix_users_google_sub'), ['google_sub'], unique=True)
    op.create_table('login_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('ip_prefix', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('login_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_login_events_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_login_events_at'), ['at'], unique=False)


def downgrade() -> None:
    op.drop_table('login_events')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_google_sub'))
        batch_op.drop_column('login_count')
        batch_op.drop_column('last_login_at')
        batch_op.drop_column('name')
        batch_op.drop_column('google_sub')
