from django.db import migrations, models


def migrate_schedule_time_to_cron(apps, schema_editor):
    """Convert existing schedule_time values to custom_cron entries."""
    Rule = apps.get_model('monitor', 'Rule')
    to_update = []
    for rule in Rule.objects.filter(schedule_time__isnull=False):
        rule.schedule_type = 'custom_cron'
        rule.schedule_cron = f'{rule.schedule_time.minute} {rule.schedule_time.hour} * * *'
        to_update.append(rule)
    if to_update:
        Rule.objects.bulk_update(to_update, ['schedule_type', 'schedule_cron'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0004_rule_custom_sql'),
    ]

    operations = [
        migrations.AddField(
            model_name='rule',
            name='schedule_type',
            field=models.CharField(
                choices=[
                    ('disabled',    'Disabled'),
                    ('preset_1x',   'Once daily (08:00 UTC)'),
                    ('preset_2x',   'Twice daily (08:00 & 20:00 UTC)'),
                    ('preset_3x',   'Three times daily (06:00, 14:00, 22:00 UTC)'),
                    ('preset_6x',   'Six times daily (every 4 h)'),
                    ('hourly',      'Hourly'),
                    ('custom_cron', 'Custom cron expression'),
                ],
                default='disabled',
                max_length=20,
                verbose_name='Schedule',
            ),
        ),
        migrations.AddField(
            model_name='rule',
            name='schedule_cron',
            field=models.CharField(
                blank=True,
                default='',
                help_text='5-field UTC cron, e.g. 0 8 * * *. Only when schedule_type = custom_cron.',
                max_length=100,
                verbose_name='Cron expression',
            ),
        ),
        migrations.RunPython(migrate_schedule_time_to_cron, noop),
    ]
