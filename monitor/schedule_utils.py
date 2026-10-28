"""
Shared schedule utilities for DataPulse monitor.

PREDEFINED maps schedule_type choices to 5-field UTC cron strings.
Exported for use by both the management command and the schedule dashboard view.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from croniter import croniter
from django.utils import timezone

PREDEFINED: dict[str, str] = {
    'preset_1x':   '0 8 * * *',
    'preset_2x':   '0 8,20 * * *',
    'preset_3x':   '0 6,14,22 * * *',
    'preset_6x':   '0 */4 * * *',
    'hourly':      '0 * * * *',
}

_SCHEDULE_LABELS: dict[str, str] = {
    'preset_1x':  'Every day at 08:00 UTC',
    'preset_2x':  'Every day at 08:00 & 20:00 UTC',
    'preset_3x':  'Every day at 06:00, 14:00, 22:00 UTC',
    'preset_6x':  'Every 4 hours',
    'hourly':     'Every hour',
    'disabled':   'Disabled',
}


def resolve_cron(rule) -> str | None:
    """Return the cron expression for rule, or None if unresolvable."""
    if rule.schedule_type == 'disabled':
        return None
    cron = PREDEFINED.get(rule.schedule_type) or rule.schedule_cron
    return cron or None


def get_next_run(rule) -> datetime | None:
    """Return the next scheduled UTC datetime for rule, or None if disabled/invalid."""
    cron_str = resolve_cron(rule)
    if not cron_str:
        return None
    now = timezone.now()
    try:
        return croniter(cron_str, now).get_next(datetime)
    except (ValueError, TypeError):
        return None


def get_schedule_label(rule) -> str:
    """Return a human-readable label for the rule's schedule type."""
    stype = rule.schedule_type
    if stype == 'custom_cron':
        cron = rule.schedule_cron
        return f'Custom: {cron}' if cron else 'Custom cron (no expression)'
    return _SCHEDULE_LABELS.get(stype, stype)
