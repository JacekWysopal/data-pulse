"""
Email notification service for DataPulse rule failures.

Public API:
  send_fail_notification(rule, result) -> bool
  send_digest_notification(run, failing_results, user) -> bool
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from .models import Rule
from .slack_service import send_slack_notification

logger = logging.getLogger(__name__)

COOLDOWN_HOURS = 1
DIGEST_SUMMARY_THRESHOLD = 10


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


def send_digest_notification(run, failing_results: list, user) -> bool:
    """
    Send one digest email for a completed run.

    Skips when:
      - failing_results is empty
      - user has no email address
    No cooldown — one per run is the contract.
    Returns True if sent, False if skipped or failed.
    """
    if not failing_results:
        return False

    if not getattr(user, 'email', ''):
        return False

    fail_count = sum(1 for r in failing_results if r.status == 'FAIL')
    error_count = sum(1 for r in failing_results if r.status == 'ERROR')
    total = len(failing_results)
    is_summary = total >= DIGEST_SUMMARY_THRESHOLD

    subject = f'[DataPulse] {total} rule(s) FAILED in run #{run.pk}'

    context = {
        'run': run,
        'failing_results': failing_results,
        'fail_count': fail_count,
        'error_count': error_count,
        'is_summary': is_summary,
    }

    try:
        text_body = render_to_string('monitor/email/digest_notification.txt', context)
        html_body = render_to_string('monitor/email/digest_notification.html', context)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send()
        return True

    except Exception:
        logger.error(
            'Failed to send digest notification for run %s to user %s (pk=%s)',
            run.pk,
            getattr(user, 'username', '?'),
            getattr(user, 'pk', '?'),
            exc_info=True,
        )
        return False


def notify_rule_result(rule: Rule, result) -> dict:
    """
    Coordinate all outbound notifications for a rule result.

    Calls both email and Slack senders and returns a dict with channel outcomes.
    Never raises; both callees handle their own exceptions.

    Returns {'email': bool, 'slack': bool}.
    """
    # INFO: log only, never notify
    if rule.severity == Rule.Severity.INFO:
        logger.debug(
            'Skipping notification for INFO rule %s (pk=%s)', rule.name, rule.pk
        )
        return {'email': False, 'slack': False}

    # WARNING: defer until 3 consecutive failures
    if rule.severity == Rule.Severity.WARNING and rule.consecutive_fails < 3:
        logger.debug(
            'Deferring WARNING notification for rule %s (pk=%s): consecutive_fails=%s',
            rule.name, rule.pk, rule.consecutive_fails,
        )
        return {'email': False, 'slack': False}

    email_sent = send_fail_notification(rule, result)
    slack_sent = send_slack_notification(rule, result)
    return {'email': email_sent, 'slack': slack_sent}
