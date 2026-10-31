"""The bootcamp seed is content, and content that silently shrinks is a bug.

Two things are worth locking down: the camps carry the design's full curriculum
and resource pack (20 lessons, 14 files, the design's own durations), and
re-running the command does not duplicate a single row — the identity is
`(venue, starts_on)`, not the title.
"""
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import (
    BootcampProfile,
    Course,
    CourseDiscussion,
    CourseResource,
    Lesson,
    Role,
    User,
)


class SeedBootcampsTests(TestCase):
    def setUp(self):
        self.lead = User.objects.create_user(
            email='lead@example.com',
            name='Lead',
            role=Role.objects.get(name='instructor'),
            verification_status='verified',
        )
        User.objects.create_user(
            email='student@skillsikka.com',
            name='Student',
            role=Role.objects.get(name='student'),
        )

    def seed(self):
        out = StringIO()
        call_command('seed_bootcamps', stdout=out)
        return out.getvalue()

    def test_both_runs_are_created_with_the_design_curriculum(self):
        self.seed()

        sundar = Course.objects.get(course_type='bootcamp', bootcamp_profile__venue_name='Sundarbazar')
        palungtar = Course.objects.get(course_type='bootcamp', bootcamp_profile__venue_name='Palungtar')

        self.assertEqual(sundar.bootcamp_profile.days, 4)
        self.assertEqual(palungtar.bootcamp_profile.days, 7)
        self.assertEqual(sundar.bootcamp_profile.status, 'completed')
        self.assertEqual(palungtar.bootcamp_profile.status, 'upcoming')
        self.assertTrue(sundar.is_published)
        self.assertFalse(sundar.is_paid)

        for course in (sundar, palungtar):
            lessons = Lesson.objects.filter(course=course).order_by('order')
            self.assertEqual(lessons.count(), 20)
            # The design authored durations as mm:ss; the first is 22:10.
            self.assertEqual(lessons.first().duration_seconds, 1330)
            self.assertEqual(lessons.first().title, 'Welcome and bootcamp orientation')
            self.assertEqual(lessons.first().section, 'Digital Foundations')
            self.assertEqual(CourseResource.objects.filter(course=course).count(), 14)
            self.assertEqual(
                CourseResource.objects.filter(course=course, section='Section 2: Design Tools & Assets').count(),
                5,
            )

    def test_the_run_length_decides_the_day_split(self):
        self.seed()

        sundar = Course.objects.get(bootcamp_profile__venue_name='Sundarbazar')
        palungtar = Course.objects.get(bootcamp_profile__venue_name='Palungtar')

        sundar_days = [lesson.day_number for lesson in sundar.lessons.order_by('order')]
        palungtar_days = [lesson.day_number for lesson in palungtar.lessons.order_by('order')]

        self.assertEqual(sundar_days, [1] * 5 + [2] * 5 + [3] * 5 + [4] * 5)
        self.assertEqual(palungtar_days, [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6, 7, 7])

    def test_rerunning_updates_instead_of_duplicating(self):
        self.seed()
        self.seed()

        self.assertEqual(Course.objects.filter(course_type='bootcamp').count(), 2)
        self.assertEqual(BootcampProfile.objects.count(), 2)
        self.assertEqual(Lesson.objects.count(), 40)
        self.assertEqual(CourseResource.objects.count(), 28)
        self.assertEqual(CourseDiscussion.objects.filter(parent=None).count(), 20)

    def test_a_renamed_camp_is_found_by_venue_and_date_not_title(self):
        self.seed()
        Course.objects.filter(bootcamp_profile__venue_name='Sundarbazar').update(title='Renamed')

        self.seed()

        self.assertEqual(Course.objects.filter(course_type='bootcamp').count(), 2)
        # …and the command puts the title back, because it owns the fixture.
        self.assertTrue(
            Course.objects.filter(title='ICT & AI BOOTCAMP at Sundarbazar').exists()
        )

    def test_no_verified_instructor_means_no_courses(self):
        self.lead.verification_status = 'pending'
        self.lead.save(update_fields=['verification_status'])

        with self.assertRaises(CommandError):
            self.seed()

        self.assertFalse(Course.objects.filter(course_type='bootcamp').exists())

    def test_the_completed_camp_has_the_demo_student_enrolled(self):
        self.seed()

        sundar = Course.objects.get(bootcamp_profile__venue_name='Sundarbazar')
        palungtar = Course.objects.get(bootcamp_profile__venue_name='Palungtar')

        self.assertEqual(sundar.enrollments.count(), 1)
        self.assertEqual(sundar.enrollments.first().status, 'active')
        # The upcoming camp is left alone: nobody has joined it yet.
        self.assertEqual(palungtar.enrollments.count(), 0)

    def test_dates_are_stable_across_runs(self):
        self.seed()
        sundar = Course.objects.get(bootcamp_profile__venue_name='Sundarbazar')
        self.assertEqual(sundar.bootcamp_profile.starts_on, date(2026, 10, 19))
        self.assertEqual(sundar.bootcamp_profile.ends_on, date(2026, 10, 22))
