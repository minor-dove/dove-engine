"""stress sessions, item responses, device state

Revision ID: 002_stress_and_device_state
Revises: 001_initial_schema
Create Date: 2026-11-07 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002_stress_and_device_state'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stress_sessions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('device_id', sa.String(length=64), sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('conversation_session_id', sa.String(length=36),
                  sa.ForeignKey('conversation_sessions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('local_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('item_plan', sa.Text(), nullable=False),
        sa.Column('current_index', sa.Integer(), nullable=False),
        sa.Column('clarify_used', sa.Boolean(), nullable=False),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_stress_sessions_device_id', 'stress_sessions', ['device_id'])
    op.create_index('ix_stress_sessions_local_date', 'stress_sessions', ['local_date'])
    op.create_index('ix_stress_sessions_device_date', 'stress_sessions', ['device_id', 'local_date'])

    op.create_table(
        'stress_item_responses',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('session_id', sa.String(length=36), sa.ForeignKey('stress_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('value', sa.Integer(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('evidence', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_stress_item_responses_session_id', 'stress_item_responses', ['session_id'])

    op.create_table(
        'device_states',
        sa.Column('device_id', sa.String(length=64), sa.ForeignKey('devices.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('present', sa.Boolean(), nullable=False),
        sa.Column('present_since', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_present_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('privacy_on', sa.Boolean(), nullable=False),
        sa.Column('privacy_since', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('device_states')
    op.drop_index('ix_stress_item_responses_session_id', table_name='stress_item_responses')
    op.drop_table('stress_item_responses')
    op.drop_index('ix_stress_sessions_device_date', table_name='stress_sessions')
    op.drop_index('ix_stress_sessions_local_date', table_name='stress_sessions')
    op.drop_index('ix_stress_sessions_device_id', table_name='stress_sessions')
    op.drop_table('stress_sessions')
