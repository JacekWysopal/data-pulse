"""
Slack notification service for DataPulse rule failures.

Public API: send_slack_notification(rule, result) -> bool
"""
import json
import logging
import urllib.error
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Rule, SlackWebhook

logger = logging.getLogger(__name__)

COOLDOWN_HOURS = 1


def _build_view_url(rule: Rule) -> str:
    """Return absolute URL to rule history, or empty string when BASE_URL is not set."""
    base_url = getattr(settings, 'BASE_URL', '') or ''
    base_url = base_url.rstrip('/')
    if not base_url:
        return ''
    path = reverse('monitor:rule_history', args=[rule.pk])
    return f'{base_url}{path}'


def send_slack_notification(rule: Rule, result) -> bool:
    """
    Send a Slack Block Kit failure notification for a rule result.

    Returns True if the message was posted, False if skipped or failed.

    Skips silently when:
      - rule.notify_slack is False
      - no enabled SlackWebhook exists for the rule owner
      - last Slack notification was < COOLDOWN_HOURS ago
    Logs at ERROR level (does not raise) on send failure.
    """
    # Guard: flag
    if not rule.notify_slack:
        return False

    # Guard: webhook must exist and be enabled
    webhook = SlackWebhook.objects.filter(user=rule.user, enabled=True).first()
    if webhook is None:
        return False

    # Guard: cooldown
    if rule.last_slack_notified_at is not None:
        if timezone.now() - rule.last_slack_notified_at < timedelta(hours=COOLDOWN_HOURS):
            return False

    # Build payload
    fallback_text = f'[DataPulse] {rule.name} \u2014 {result.status}'

    measured_str = '—'
    if result.row_count is not None:
        measured_str = f'{result.row_count:,} rows'
    elif result.last_record_age_hours is not None:
        measured_str = f'{result.last_record_age_hours:.1f} h age'

    threshold_str = '—'
    if rule.min_row_count is not None:
        threshold_str = f'≥ {rule.min_row_count:,} rows'
    elif rule.max_age_hours is not None:
        threshold_str = f'≤ {rule.max_age_hours} h age'

    blocks = [
        {
            'type': 'section',
            'text': {
                'type': 'mrkdwn',
                'text': (
                    f'*[DataPulse]* Rule *{rule.name}* returned '
                    f'*{result.status}*'
                ),
            },
        },
        {
            'type': 'section',
            'fields': [
                {'type': 'mrkdwn', 'text': f'*Rule*\n{rule.name}'},
                {'type': 'mrkdwn', 'text': f'*Status*\n{result.status}'},
                {'type': 'mrkdwn', 'text': f'*Measured*\n{measured_str}'},
                {'type': 'mrkdwn', 'text': f'*Threshold*\n{threshold_str}'},
            ],
        },
    ]

    view_url = _build_view_url(rule)
    if view_url:
        blocks.append({
            'type': 'actions',
            'elements': [
                {
                    'type': 'button',
                    'text': {'type': 'plain_text', 'text': 'View History'},
                    'url': view_url,
                }
            ],
        })

    payload = {'text': fallback_text, 'blocks': blocks}

    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            webhook.url,
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        urllib.request.urlopen(req, timeout=5)

        # Stamp cooldown without triggering auto_now on updated_at
        now = timezone.now()
        Rule.objects.filter(pk=rule.pk).update(last_slack_notified_at=now)
        rule.last_slack_notified_at = now

        return True

    except Exception:
        logger.error(
            'Failed to send Slack notification for rule %s (pk=%s)',
            rule.name,
            rule.pk,
            exc_info=True,
        )
        return False
