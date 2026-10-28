"""
Run scheduled rules — evaluate each rule's cron expression against current UTC minute.
Called by Render Cron Job every minute: python manage.py run_scheduled
"""
from croniter import croniter
from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import Rule
from monitor.schedule_utils import PREDEFINED
from monitor.services import run_single_rule


class Command(BaseCommand):
    help = 'Run rules whose cron schedule matches the current UTC minute.'

    def handle(self, *args, **options):
        now = timezone.now().replace(second=0, microsecond=0)
        rules = Rule.objects.exclude(schedule_type='disabled').select_related('connection')

        fired = 0
        for rule in rules:
            cron_str = PREDEFINED.get(rule.schedule_type) or rule.schedule_cron
            if not cron_str:
                self.stderr.write(
                    f'Rule {rule.id} has schedule_type=custom_cron but schedule_cron is blank — skipping'
                )
                continue
            try:
                matched = croniter.match(cron_str, now)
            except (ValueError, TypeError) as exc:
                self.stderr.write(
                    f'Rule {rule.id} has invalid cron expression "{cron_str}" — skipping ({exc})'
                )
                continue
            if matched:
                result = run_single_rule(rule)
                self.stdout.write(f'  [{result.status}] {rule.name}')
                fired += 1

        if fired == 0:
            self.stdout.write(f'  {now.strftime("%H:%M")} UTC — no rules matched.')
