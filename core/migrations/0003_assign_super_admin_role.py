from django.db import migrations


def assign_super_admin_role(apps, schema_editor):
    User = apps.get_model('core', 'User')
    Role = apps.get_model('core', 'Role')
    try:
        role = Role.objects.get(name='super_admin')
    except Role.DoesNotExist:
        return
    User.objects.filter(is_superuser=True).update(role=role)


class Migration(migrations.Migration):
    dependencies = [('core', '0002_seed_roles')]
    operations = [migrations.RunPython(assign_super_admin_role, migrations.RunPython.noop)]
