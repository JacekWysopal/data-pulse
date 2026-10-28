"""
Email notification service for DataPulse rule failures.

Public API: send_fail_notification(rule, result) -> bool
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Rule

logger = logging.getLogger(__name__)

COOLDOWN_HOURS = 1


def send_fail_notification(rule: Rule, result) -> bool:
    """
    Send a failure notification email for a rule result.

    Returns True if email was sent, False if skipped or failed.

    Skips silently when:
      - rule.notify_on_fail is False
      - rule.user is None or rule.user.email is blank
      - last notification was < COOLDOWN_HOURS ago
    Logs at ERROR level (does not raise) on send failure.
    """
    if not rule.notify_on_fail:
        return False

    # Guard: owner must exist and have an email address
    if not rule.user or not getattr(rule.user, 'email', ''):
        return False

    # Guard: cooldown — skip if last email was sent less than 1 hour ago
    if rule.last_notified_at is not None:
        if timezone.now() - rule.last_notified_at < timedelta(hours=COOLDOWN_HOURS):
            return False

    context = {'rule': rule, 'result': result}
    subject = f'[DataPulse] {rule.name} \u2014 {result.status}'

    try:
        text_body = render_to_string('monitor/email/fail_notification.txt', context)
        html_body = render_to_string('monitor/email/fail_notification.html', context)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[rule.user.email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send()

        # Update cooldown timestamp without triggering auto_now on updated_at
        Rule.objects.filter(pk=rule.pk).update(last_notified_at=timezone.now())
        rule.last_notified_at = timezone.now()

        return True

    except Exception:
        logger.error(
            'Failed to send failure notification for rule %s (pk=%s)',
            rule.name,
            rule.pk,
            exc_info=True,
        )
        return False
