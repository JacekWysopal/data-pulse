"""
Management command: assign_existing_to_superuser

Assigns all Rule and Connection records that have no user (user=None)
to the first superuser ordered by pk. Useful when running this as a
standalone step after deploying migration 0009 to an existing database.

Usage:
    python manage.py assign_existing_to_superuser
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from monitor.models import Connection, Rule


class Command(BaseCommand):
    help = 'Assign all Rule and Connection records without a user to the first superuser.'

    def handle(self, *args, **options):
        User = get_user_model()
        superuser = User.objects.filter(is_superuser=True).order_by('pk').first()
        if not superuser:
            self.stderr.write('No superuser found. Create one with: python manage.py createsuperuser')
            return

        rules_updated = Rule.objects.filter(user=None).update(user=superuser)
        conns_updated = Connection.objects.filter(user=None).update(user=superuser)

        self.stdout.write(
            self.style.SUCCESS(
                f'Assigned {rules_updated} Rule(s) and {conns_updated} Connection(s) '
                f'to superuser "{superuser.username}" (pk={superuser.pk}).'
            )
        )
