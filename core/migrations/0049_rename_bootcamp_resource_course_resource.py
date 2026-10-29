"""Rename BootcampResource to CourseResource and make it per-lesson.

The table was bootcamp-scoped while the endpoint behind it is the player's
Resources tab, which every course type renders — so `GET
/courses/{id}/resources/` 404'd every course the builder can create. The rename
opens it to all courses; the new nullable `lesson` is what lets the builder
attach files while editing a lesson.

**Written by hand, not generated.** `makemigrations` saw a new class and a
deleted one and proposed Create + Delete, which would have dropped every file
row. `RenameModel` moves the table in one step (the new model carries
`db_table='course_resources'`, so Django renames rather than copies), the
`AlterField` only touches `related_name`, and `AddField` adds a nullable column
— no data moves and no existing row is touched.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0048_rename_bootcamp_discussion_course_discussion'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='BootcampResource',
            new_name='CourseResource',
        ),
        migrations.AlterModelTable(
            name='courseresource',
            table='course_resources',
        ),
        migrations.AlterField(
            model_name='courseresource',
            name='course',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='course_resources',
                to='core.course',
            ),
        ),
        migrations.AddField(
            model_name='courseresource',
            name='lesson',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='resources',
                to='core.lesson',
            ),
        ),
    ]
