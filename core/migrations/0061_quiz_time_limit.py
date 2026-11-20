from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0060_module_quiz'),
    ]

    operations = [
        migrations.AddField(
            model_name='quiz',
            name='time_limit_seconds',
            field=models.PositiveSmallIntegerField(default=180),
        ),
    ]
