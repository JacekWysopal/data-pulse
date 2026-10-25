"""
Seed command — wypełnia bazę przykładowymi regułami i historią wyników.
Uruchomienie: python manage.py seed_demo
Idempotentny — nie tworzy duplikatów jeśli reguły już istnieją.
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import CheckRun, Rule, RuleResult


RULES = [
    # (name, schema, table, timestamp_col, max_age_h, min_rows)
    ('orders_freshness',      'public',    'orders',           'created_at',   1,   100),
    ('users_volume',          'public',    'users',            None,           None, 500),
    ('events_log',            'analytics', 'events',           'logged_at',    2,   None),
    ('products_sync',         'public',    'products',         'synced_at',    24,  50),
    ('payments_freshness',    'finance',   'payments',         'paid_at',      6,   10),
    ('sessions_volume',       'public',    'sessions',         None,           None, 1000),
    ('alerts_log',            'ops',       'alerts',           'triggered_at', 1,   None),
    ('inventory_snapshot',    'warehouse', 'inventory',        'snapshot_at',  48,  200),
    ('dim_customers',         'dw',        'dim_customers',    None,           None, 5000),
    ('fact_sales_daily',      'dw',        'fact_sales',       'sale_date',    25,  None),
    ('api_logs',              'logs',      'api_requests',     'ts',           1,   None),
    ('reports_cache',         'cache',     'report_snapshots', 'generated_at', 12,  None),
]


def _make_result(run, rule, status, row_count=None, age_hours=None, error=''):
    RuleResult.objects.create(
        run=run,
        rule=rule,
        checked_at=run.started_at + timedelta(seconds=random.randint(0, 30)),
        status=status,
        row_count=row_count,
        last_record_age_hours=age_hours,
        error_message=error,
    )


class Command(BaseCommand):
    help = 'Seed demo rules and check history'

    def handle(self, *args, **options):
        created = 0

        # 1. Utwórz reguły
        rule_objs = []
        for name, schema, table, ts_col, max_age, min_rows in RULES:
            rule, new = Rule.objects.get_or_create(
                name=name,
                defaults=dict(
                    schema_name=schema,
                    table_name=table,
                    timestamp_column=ts_col or '',
                    max_age_hours=max_age,
                    min_row_count=min_rows,
                )
            )
            if new:
                created += 1
            rule_objs.append(rule)

        self.stdout.write(f'  Reguły: {created} nowych / {len(rule_objs)} łącznie')

        # 2. Czy mamy już historię?
        if CheckRun.objects.count() >= 5:
            self.stdout.write('  Historia już istnieje — pomijam.')
            return

        # 3. Generuj 8 przebiegów historycznych
        now = timezone.now()
        for i in range(8, 0, -1):
            started = now - timedelta(hours=i * 3 + random.randint(0, 30))
            run = CheckRun.objects.create(
                started_at=started,
                finished_at=started + timedelta(seconds=random.randint(4, 25)),
            )

            for rule in rule_objs:
                # Symuluj realistyczne dane
                rng = random.random()

                if rule.name == 'users_volume':
                    # Czasem FAIL (za mało)
                    count = random.randint(420, 600)
                    status = 'OK' if count >= (rule.min_row_count or 0) else 'FAIL'
                    _make_result(run, rule, status, row_count=count)

                elif rule.name == 'events_log':
                    # Czasem ERROR (brak połączenia)
                    if rng < 0.15:
                        _make_result(run, rule, 'ERROR', error='connection refused: analytics host unreachable')
                    else:
                        age = round(random.uniform(0.1, 4.0), 2)
                        status = 'OK' if age <= (rule.max_age_hours or 999) else 'FAIL'
                        _make_result(run, rule, status, age_hours=age)

                elif rule.name in ('api_logs', 'alerts_log'):
                    # Szybkie tabele — prawie zawsze świeże
                    age = round(random.uniform(0.0, 1.5), 2)
                    status = 'OK' if age <= (rule.max_age_hours or 999) else 'FAIL'
                    _make_result(run, rule, status, age_hours=age)

                elif rule.name == 'dim_customers':
                    count = random.randint(4800, 6500)
                    status = 'OK' if count >= (rule.min_row_count or 0) else 'FAIL'
                    _make_result(run, rule, status, row_count=count)

                elif rule.timestamp_column and rule.min_row_count:
                    # Obie reguły
                    count = random.randint(
                        int((rule.min_row_count or 10) * 0.8),
                        int((rule.min_row_count or 10) * 2.5),
                    )
                    age = round(random.uniform(0.1, (rule.max_age_hours or 24) * 1.3), 2)
                    vol_ok = count >= (rule.min_row_count or 0)
                    age_ok = age <= (rule.max_age_hours or 999)
                    status = 'OK' if (vol_ok and age_ok) else 'FAIL'
                    _make_result(run, rule, status, row_count=count, age_hours=age)

                elif rule.timestamp_column:
                    age = round(random.uniform(0.1, (rule.max_age_hours or 24) * 1.3), 2)
                    status = 'OK' if age <= (rule.max_age_hours or 999) else 'FAIL'
                    _make_result(run, rule, status, age_hours=age)

                else:
                    count = random.randint(
                        int((rule.min_row_count or 100) * 0.7),
                        int((rule.min_row_count or 100) * 3),
                    )
                    status = 'OK' if count >= (rule.min_row_count or 0) else 'FAIL'
                    _make_result(run, rule, status, row_count=count)

        self.stdout.write(self.style.SUCCESS(f'  Seed gotowy — {CheckRun.objects.count()} przebiegów w bazie.'))
