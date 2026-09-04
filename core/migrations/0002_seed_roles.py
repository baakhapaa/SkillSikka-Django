from django.db import migrations


ROLES = {
    'student': 'Learner account',
    'instructor': 'Instructor account',
    'school_admin': 'School administrator',
    'local_authority': 'Local authority administrator',
    'ministry': 'Ministry administrator',
    'super_admin': 'Full platform administrator',
}
PERMISSIONS = (
    'manage_courses',
    'view_ministry_dashboard',
    'verify_instructor',
    'manage_payments',
)


def seed_rbac(apps, schema_editor):
    Role = apps.get_model('core', 'Role')
    Permission = apps.get_model('core', 'Permission')
    RolePermission = apps.get_model('core', 'RolePermission')
    roles = {name: Role.objects.create(name=name, description=description) for name, description in ROLES.items()}
    permissions = {name: Permission.objects.create(name=name) for name in PERMISSIONS}
    for role_name, permission_names in {
        'instructor': ('manage_courses',),
        'school_admin': ('manage_courses', 'verify_instructor', 'manage_payments'),
        'ministry': ('view_ministry_dashboard',),
        'super_admin': PERMISSIONS,
    }.items():
        RolePermission.objects.bulk_create(
            RolePermission(role=roles[role_name], permission=permissions[permission_name])
            for permission_name in permission_names
        )


def remove_rbac(apps, schema_editor):
    apps.get_model('core', 'RolePermission').objects.all().delete()
    apps.get_model('core', 'Permission').objects.all().delete()
    apps.get_model('core', 'Role').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0001_initial')]
    operations = [migrations.RunPython(seed_rbac, remove_rbac)]
