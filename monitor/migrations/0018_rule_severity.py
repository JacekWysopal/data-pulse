from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0017_apikey'),
    ]

    operations = [
        migrations.AddField(
            model_name='rule',
            name='severity',
            field=models.CharField(
                choices=[('critical', 'Critical'), ('warning', 'Warning'), ('info', 'Info')],
                default='critical',
                max_length=20,
                verbose_name='Severity',
            ),
        ),
        migrations.AddField(
            model_name='rule',
            name='consecutive_fails',
            field=models.IntegerField(
                default=0,
                help_text='Incremented on each FAIL/ERROR result; reset to 0 on OK. Used for WARNING threshold.',
                verbose_name='Consecutive failures',
            ),
        ),
    ]
