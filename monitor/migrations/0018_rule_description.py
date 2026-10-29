from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds Rule.description TextField. Column already exists in the database."""

    dependencies = [
        ('monitor', '0017_apikey'),
    ]

    operations = [
        migrations.AddField(
            model_name='rule',
            name='description',
            field=models.TextField(
                blank=True,
                default='',
                help_text='Optional note explaining why this rule exists.',
                max_length=500,
                verbose_name='Description',
            ),
            preserve_default=False,
        ),
    ]
