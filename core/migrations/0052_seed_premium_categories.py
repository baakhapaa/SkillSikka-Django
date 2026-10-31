from django.db import migrations

# The premium catalogue's own category chips, in the order the design draws them
# (`premium_courses_page.dart` — `All` is the absence of a filter, not a row).
# Seeded rather than left empty so the builder's Category picker has something to
# offer on a fresh database; an admin can rename or deactivate any of them.
CATEGORIES = [
    ('Art & Craft', 'art-craft'),
    ('Design', 'design'),
    ('Physics', 'physics'),
    ('Business', 'business'),
    ('Technology', 'technology'),
    ('Music', 'music'),
]


def seed(apps, schema_editor):
    PremiumCategory = apps.get_model('core', 'PremiumCategory')
    for order, (name, slug) in enumerate(CATEGORIES):
        PremiumCategory.objects.update_or_create(
            slug=slug,
            defaults={'name': name, 'display_order': order, 'is_active': True},
        )


def unseed(apps, schema_editor):
    PremiumCategory = apps.get_model('core', 'PremiumCategory')
    PremiumCategory.objects.filter(slug__in=[slug for _, slug in CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0051_premium_categories'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
