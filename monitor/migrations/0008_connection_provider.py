from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0007_slacknotification'),
    ]

    operations = [
        migrations.AddField(
            model_name='connection',
            name='provider',
            field=models.CharField(
                choices=[('postgresql', 'PostgreSQL'), ('mysql', 'MySQL')],
                default='postgresql',
                max_length=20,
            ),
        ),
    ]
