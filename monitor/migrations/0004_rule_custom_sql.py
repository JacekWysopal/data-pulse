from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0003_rule_schedule_time'),
    ]

    operations = [
        migrations.AddField(
            model_name='rule',
            name='rule_type',
            field=models.CharField(
                choices=[('volume_freshness', 'Volume / Freshness'), ('custom_sql', 'Custom SQL')],
                default='volume_freshness',
                max_length=30,
                verbose_name='Rule type',
            ),
        ),
        migrations.AddField(
            model_name='rule',
            name='custom_sql',
            field=models.TextField(
                blank=True,
                verbose_name='Custom SQL',
                help_text=(
                    'SELECT query returning a single boolean-like value. '
                    'true / 1 = OK, false / 0 / NULL / empty = FAIL. '
                    'Must start with SELECT.'
                ),
            ),
        ),
        migrations.AlterField(
            model_name='rule',
            name='schema_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='Schema'),
        ),
        migrations.AlterField(
            model_name='rule',
            name='table_name',
            field=models.CharField(blank=True, max_length=100, verbose_name='Table'),
        ),
        migrations.AlterConstraint(
            model_name='rule',
            name='rule_has_at_least_one_condition',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(timestamp_column__gt='', max_age_hours__isnull=False)
                    | models.Q(min_row_count__isnull=False)
                    | models.Q(rule_type='custom_sql', custom_sql__gt='')
                ),
                name='rule_has_at_least_one_condition',
            ),
        ),
    ]
