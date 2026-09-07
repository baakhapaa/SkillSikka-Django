from django.db import migrations, models
import django.db.models.deletion


def assign_missing_roles(apps, schema_editor):
	User = apps.get_model('core', 'User')
	Role = apps.get_model('core', 'Role')
	student_role = Role.objects.get(name='student')
	User.objects.filter(role__isnull=True).update(role=student_role)


class Migration(migrations.Migration):
	dependencies = [
		('core', '0007_instructorprofile_municipality_and_more'),
	]

	operations = [
		migrations.RunPython(assign_missing_roles, migrations.RunPython.noop),
		migrations.AlterField(
			model_name='user',
			name='role',
			field=models.ForeignKey(
				on_delete=django.db.models.deletion.PROTECT,
				related_name='users',
				to='core.role',
			),
		),
	]
