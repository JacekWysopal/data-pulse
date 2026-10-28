"""
Run scheduled rules — evaluate each rule's cron expression against current UTC minute.
Called by Render Cron Job every minute: python manage.py run_scheduled
"""
from croniter import croniter
from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import Rule
from monitor.services import run_single_rule

# Cron strings for predefined schedule types (UTC).
PREDEFINED = {
    'preset_1x':   '0 8 * * *',
    'preset_2x':   '0 8,20 * * *',
    'preset_3x':   '0 6,14,22 * * *',
    'preset_6x':   '0 */4 * * *',
    'hourly':      '0 * * * *',
}


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
            if croniter.match(cron_str, now):
                result = run_single_rule(rule)
                self.stdout.write(f'  [{result.status}] {rule.name}')
                fired += 1

        if fired == 0:
            self.stdout.write(f'  {now.strftime("%H:%M")} UTC — no rules matched.')
