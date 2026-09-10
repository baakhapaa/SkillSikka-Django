from django.db import migrations


GRADES = [f'Grade {n}' for n in range(1, 13)]


def seed_grades(apps, schema_editor):
	Grade = apps.get_model('core', 'Grade')
	for name in GRADES:
		Grade.objects.get_or_create(name=name)


def unseed_grades(apps, schema_editor):
	Grade = apps.get_model('core', 'Grade')
	Grade.objects.filter(name__in=GRADES).delete()


class Migration(migrations.Migration):

	dependencies = [
		('core', '0012_passwordresetotp'),
	]

	operations = [
		migrations.RunPython(seed_grades, unseed_grades),
	]