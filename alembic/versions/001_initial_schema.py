"""initial schema

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-10-03 21:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. devices
    op.create_table(
        'devices',
        sa.Column('id', sa.String(length=64), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('firmware_version', sa.String(length=32), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_devices_id', 'devices', ['id'])

    # 2. mood_events
    op.create_table(
        'mood_events',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('event_id', sa.String(length=128), nullable=False),
        sa.Column('device_id', sa.String(length=64), sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('mood_id', sa.Integer(), nullable=False),
        sa.Column('emotion', sa.String(length=32), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_valid', sa.Boolean(), nullable=False, server_default='1')
    )
    op.create_index('ix_mood_events_event_id', 'mood_events', ['event_id'], unique=True)
    op.create_index('ix_mood_events_device_recorded', 'mood_events', ['device_id', 'recorded_at'])

    # 3. mood_streaks
    op.create_table(
        'mood_streaks',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('device_id', sa.String(length=64), sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('mood_id', sa.Integer(), nullable=False),
        sa.Column('emotion', sa.String(length=32), nullable=False),
        sa.Column('current_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_event_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('qualifying_streak_triggered', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_mood_streaks_device_mood', 'mood_streaks', ['device_id', 'mood_id'], unique=True)

    # 4. proactive_cooldowns
    op.create_table(
        'proactive_cooldowns',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('device_id', sa.String(length=64), sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('last_proactive_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cooldown_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_trigger_type', sa.String(length=64), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_proactive_cooldowns_device_id', 'proactive_cooldowns', ['device_id'], unique=True)

    # 5. conversation_starters
    op.create_table(
        'conversation_starters',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('text', sa.String(length=512), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_starters_category_active', 'conversation_starters', ['category', 'is_active'])

    # 6. proactive_trigger_logs
    op.create_table(
        'proactive_trigger_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('device_id', sa.String(length=64), sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('trigger_type', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('reason', sa.String(length=256), nullable=True),
        sa.Column('starter_id', sa.Integer(), sa.ForeignKey('conversation_starters.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_proactive_logs_device_created', 'proactive_trigger_logs', ['device_id', 'created_at'])

    # 7. conversation_sessions
    op.create_table(
        'conversation_sessions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('device_id', sa.String(length=64), sa.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('trigger_type', sa.String(length=64), nullable=False, server_default='user_initiated'),
        sa.Column('is_false_trigger', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index('ix_sessions_device_id', 'conversation_sessions', ['device_id'])
    op.create_index('ix_sessions_active', 'conversation_sessions', ['is_active'])

    # 8. conversation_messages
    op.create_table(
        'conversation_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('session_id', sa.String(length=36), sa.ForeignKey('conversation_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('mood_context', sa.String(length=32), nullable=True),
        sa.Column('delivery_status', sa.String(length=32), nullable=False, server_default='delivered'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_messages_session_id', 'conversation_messages', ['session_id'])

    # 9. long_term_memories
    op.create_table(
        'long_term_memories',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('session_id', sa.String(length=36), sa.ForeignKey('conversation_sessions.id', ondelete='CASCADE'), nullable=True),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('is_false_trigger', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_memories_session_id', 'long_term_memories', ['session_id'])
    op.create_index('ix_memories_active', 'long_term_memories', ['is_active'])

    # 10. tasks
    op.create_table(
        'tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('title', sa.String(length=256), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_tasks_status_due', 'tasks', ['status', 'due_date'])

    # 11. reminders
    op.create_table(
        'reminders',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('message', sa.String(length=512), nullable=False),
        sa.Column('scheduled_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('ix_reminders_status_time', 'reminders', ['status', 'scheduled_time'])

    # 12. user_preferences
    op.create_table(
        'user_preferences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('quiet_hours_start', sa.String(length=8), nullable=False, server_default='22:00'),
        sa.Column('quiet_hours_end', sa.String(length=8), nullable=False, server_default='07:00'),
        sa.Column('proactive_enabled', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('cooldown_minutes', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='Asia/Kolkata'),
        sa.Column('morning_time', sa.String(length=8), nullable=False, server_default='08:00'),
        sa.Column('midday_time', sa.String(length=8), nullable=False, server_default='13:00'),
        sa.Column('evening_time', sa.String(length=8), nullable=False, server_default='19:00'),
        sa.Column('night_time', sa.String(length=8), nullable=False, server_default='22:30'),
        sa.Column('night_enabled', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)
    )

    # 13. routine_executions
    op.create_table(
        'routine_executions',
        sa.Column('id', sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column('routine_type', sa.String(length=32), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='completed')
    )
    op.create_index('ix_routines_type_date', 'routine_executions', ['routine_type', 'scheduled_for'])


def downgrade() -> None:
    op.drop_table('routine_executions')
    op.drop_table('user_preferences')
    op.drop_table('reminders')
    op.drop_table('tasks')
    op.drop_table('long_term_memories')
    op.drop_table('conversation_messages')
    op.drop_table('conversation_sessions')
    op.drop_table('proactive_trigger_logs')
    op.drop_table('conversation_starters')
    op.drop_table('proactive_cooldowns')
    op.drop_table('mood_streaks')
    op.drop_table('mood_events')
    op.drop_table('devices')
