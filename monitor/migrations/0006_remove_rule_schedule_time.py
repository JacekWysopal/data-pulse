from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0005_rule_schedule_type_cron'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='rule',
            name='schedule_time',
        ),
    ]
