from django.db import migrations, models


class Migration(migrations.Migration):
    """Add notify_on_fail and last_notified_at fields to Rule.

    notify_on_fail defaults to False — all existing rules are opt-out.
    last_notified_at defaults to NULL — no cooldown applies until first send.
    """

    dependencies = [
        ('monitor', '0011_user_fk_required'),
    ]

    operations = [
        migrations.AddField(
            model_name='rule',
            name='notify_on_fail',
            field=models.BooleanField(
                default=False,
                help_text='Send an email to the rule owner when this rule returns FAIL or ERROR.',
                verbose_name='Notify on failure',
            ),
        ),
        migrations.AddField(
            model_name='rule',
            name='last_notified_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Last notified at',
            ),
        ),
    ]
