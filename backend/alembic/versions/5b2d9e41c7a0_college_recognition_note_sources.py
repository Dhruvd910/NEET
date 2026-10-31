"""college recognition note, contact details, website and location sources

Revision ID: 5b2d9e41c7a0
Revises: 3f4ffdd3c71b
Create Date: 2026-10-31 17:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5b2d9e41c7a0'
down_revision: Union[str, Sequence[str], None] = '3f4ffdd3c71b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('colleges', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recognition_note', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('pincode', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('contact_email', sa.String(length=254), nullable=True))
        batch_op.add_column(sa.Column('contact_phone', sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column('website_source', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('location_source', sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('colleges', schema=None) as batch_op:
        batch_op.drop_column('contact_phone')
        batch_op.drop_column('contact_email')
        batch_op.drop_column('pincode')
        batch_op.drop_column('location_source')
        batch_op.drop_column('website_source')
        batch_op.drop_column('recognition_note')
