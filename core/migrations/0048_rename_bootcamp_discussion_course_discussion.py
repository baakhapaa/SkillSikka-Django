"""Rename BootcampDiscussion to CourseDiscussion.

The table and the class were bootcamp-scoped while the endpoint behind them is
the player's Q&A tab, which every course type renders. The rename is the honest
half of opening that endpoint to all courses.

**Written by hand, not generated.** `makemigrations` saw a new class and a
deleted one and proposed Create + Delete, which would have dropped every thread.
`RenameModel` moves the table in one step (the new model carries
`db_table='course_discussions'`, so Django renames rather than copies), and the
`AlterField`s below only touch `related_name`/target metadata — no columns move.
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0047_course_language_course_level'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='BootcampDiscussion',
            new_name='CourseDiscussion',
        ),
        migrations.AlterModelTable(
            name='coursediscussion',
            table='course_discussions',
        ),
        migrations.AlterField(
            model_name='coursediscussion',
            name='course',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='course_discussions',
                to='core.course',
            ),
        ),
        migrations.AlterField(
            model_name='coursediscussion',
            name='author',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='course_discussions',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='discussionlike',
            name='discussion',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='likes',
                to='core.coursediscussion',
            ),
        ),
        migrations.AlterField(
            model_name='discussionlike',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='course_discussion_likes',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
