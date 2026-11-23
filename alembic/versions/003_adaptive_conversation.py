"""adaptive conversation: user profile + per-session conversation state

Revision ID: 003_adaptive_conversation
Revises: 002_stress_and_device_state
Create Date: 2026-11-23 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '003_adaptive_conversation'
down_revision: Union[str, None] = '002_stress_and_device_state'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_profiles',
        sa.Column('device_id', sa.String(length=64), sa.ForeignKey('devices.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('data', sa.Text(), nullable=False),
        sa.Column('sessions_count', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column('stress_sessions', sa.Column('daypart', sa.String(length=16), nullable=True))
    op.add_column('stress_sessions', sa.Column('window', sa.String(length=32), nullable=True))
    op.add_column('stress_sessions', sa.Column('followups_used', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('stress_sessions', sa.Column('awaiting_followup', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('stress_sessions', sa.Column('summary', sa.Text(), nullable=True))


def downgrade() -> None:
    for c in ('summary', 'awaiting_followup', 'followups_used', 'window', 'daypart'):
        op.drop_column('stress_sessions', c)
    op.drop_table('user_profiles')
