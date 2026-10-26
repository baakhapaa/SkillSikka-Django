from django.db import migrations


def seed_categories(apps, schema_editor):
    interests = apps.get_model('core', 'LearningInterest').objects.using(schema_editor.connection.alias)
    for order, (name, slug) in enumerate((('Drawing', 'drawing'), ('Public Speaking', 'public-speaking'), ('Music', 'music')), 13):
        if not interests.filter(name__iexact=name).exists():
            interests.get_or_create(slug=slug, defaults={'name': name, 'display_order': order})


class Migration(migrations.Migration):
    dependencies = [('core', '0043_course_skill_category_lesson_duration_seconds_and_more')]
    operations = [migrations.RunPython(seed_categories, migrations.RunPython.noop)]
