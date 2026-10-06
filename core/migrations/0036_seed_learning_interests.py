from django.db import migrations


INITIAL_INTERESTS = (
    ('Coding', 'coding'),
    ('Mathematics', 'mathematics'),
    ('Physics', 'physics'),
    ('Chemistry', 'chemistry'),
    ('Biology', 'biology'),
    ('Data Science', 'data-science'),
    ('AI & ML', 'ai-ml'),
    ('Web Dev', 'web-dev'),
    ('App Dev', 'app-dev'),
    ('Robotics', 'robotics'),
    ('Electronics', 'electronics'),
    ('3D Design', '3d-design'),
)


def seed_interests_and_profile_stage(apps, schema_editor):
    alias = schema_editor.connection.alias
    interest_model = apps.get_model('core', 'LearningInterest')
    for display_order, (name, slug) in enumerate(INITIAL_INTERESTS, start=1):
        interest_model.objects.using(alias).get_or_create(
            slug=slug,
            defaults={'name': name, 'display_order': display_order, 'description': '', 'is_active': True},
        )
    # Preserve user flags and steps. Existing completed students have already
    # completed the validated profile stage; incomplete students keep their state.
    apps.get_model('core', 'StudentProfile').objects.using(alias).filter(
        user__onboarding_completed=True,
    ).update(profile_completed=True)


class Migration(migrations.Migration):
    dependencies = [('core', '0035_learning_interests_student_onboarding')]
    operations = [migrations.RunPython(seed_interests_and_profile_stage, migrations.RunPython.noop)]
