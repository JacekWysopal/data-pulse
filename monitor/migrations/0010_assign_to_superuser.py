from django.db import migrations


def assign_to_superuser(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Rule = apps.get_model('monitor', 'Rule')
    Connection = apps.get_model('monitor', 'Connection')
    superuser = User.objects.filter(is_superuser=True).order_by('pk').first()
    if superuser:
        Rule.objects.filter(user=None).update(user=superuser)
        Connection.objects.filter(user=None).update(user=superuser)


def reverse_assign(apps, schema_editor):
    # Irreversible data migration; reverse is a no-op
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('monitor', '0009_user_fk_nullable'),
    ]

    operations = [
        migrations.RunPython(assign_to_superuser, reverse_assign),
    ]
