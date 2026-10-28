"""
Run scheduled rules — execute rules whose schedule_time matches current UTC hour:minute.
Called by Render Cron Job every minute: python manage.py run_scheduled
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import Rule
from monitor.services import run_single_rule


class Command(BaseCommand):
    help = 'Run rules scheduled for the current UTC time (HH:MM).'

    def handle(self, *args, **options):
        now = timezone.now().time().replace(second=0, microsecond=0)
        rules = Rule.objects.filter(schedule_time=now).select_related('connection')

        if not rules.exists():
            self.stdout.write(f'  {now.strftime("%H:%M")} UTC — no rules scheduled.')
            return

        self.stdout.write(f'  {now.strftime("%H:%M")} UTC — running {rules.count()} rule(s)...')
        for rule in rules:
            result = run_single_rule(rule)
            self.stdout.write(f'    [{result.status}] {rule.name}')
