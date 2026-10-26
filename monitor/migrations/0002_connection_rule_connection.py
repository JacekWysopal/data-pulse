from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0001_initial'),
    ]

    operations = [
        # 1. Create Connection table
        migrations.CreateModel(
            name='Connection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
                ('description', models.CharField(blank=True, max_length=500)),
                ('database_url', models.TextField(db_column='database_url')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),

        # 2. Add connection FK to Rule (nullable)
        migrations.AddField(
            model_name='rule',
            name='connection',
            field=models.ForeignKey(
                blank=True,
                help_text='Leave empty to use the default MONITORED_DATABASE_URL from environment.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='rules',
                to='monitor.connection',
                verbose_name='Connection',
            ),
        ),

        # 3. Update verbose_name on existing Rule fields (no DB change)
        migrations.AlterField(
            model_name='rule',
            name='name',
            field=models.CharField(max_length=200, verbose_name='Rule name'),
        ),
        migrations.AlterField(
            model_name='rule',
            name='schema_name',
            field=models.CharField(max_length=100, verbose_name='Schema'),
        ),
        migrations.AlterField(
            model_name='rule',
            name='table_name',
            field=models.CharField(max_length=100, verbose_name='Table'),
        ),
        migrations.AlterField(
            model_name='rule',
            name='timestamp_column',
            field=models.CharField(
                blank=True,
                help_text='Column name for freshness check (optional)',
                max_length=100,
                verbose_name='Timestamp column',
            ),
        ),
        migrations.AlterField(
            model_name='rule',
            name='max_age_hours',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Max record age (hours)'),
        ),
        migrations.AlterField(
            model_name='rule',
            name='min_row_count',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='Min row count'),
        ),
    ]
