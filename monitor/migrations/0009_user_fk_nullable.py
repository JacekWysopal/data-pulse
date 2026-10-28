from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0008_connection_provider'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add nullable user FK to Connection
        migrations.AddField(
            model_name='connection',
            name='user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='connections',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # Remove global unique=True on Connection.name, add unique_together
        migrations.AlterField(
            model_name='connection',
            name='name',
            field=models.CharField(max_length=200),
        ),
        migrations.AlterUniqueTogether(
            name='connection',
            unique_together={('user', 'name')},
        ),
        # Add nullable user FK to Rule
        migrations.AddField(
            model_name='rule',
            name='user',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='rules',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
