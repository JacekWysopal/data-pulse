from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """Make user FK non-nullable on Rule and Connection.

    Must be deployed together with the Phase 3 view changes that always
    set user=request.user on rule_create and connection_create. Deploying
    this migration without the updated views would cause IntegrityError.
    """

    dependencies = [
        ('monitor', '0010_assign_to_superuser'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='rule',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='rules',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='connection',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='connections',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
