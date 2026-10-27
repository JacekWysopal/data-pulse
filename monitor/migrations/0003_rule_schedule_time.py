from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0002_connection_rule_connection'),
    ]

    operations = [
        migrations.AddField(
            model_name='rule',
            name='schedule_time',
            field=models.TimeField(
                blank=True,
                null=True,
                verbose_name='Schedule time (UTC)',
                help_text='Daily run time in UTC, e.g. 06:00. Leave empty to run manually only.',
            ),
        ),
    ]
