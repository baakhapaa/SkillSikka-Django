"""The bootcamp is admin-only, and the dashboard is where an admin adds one.

These tests cover the path a human actually takes: sign in as an administrator,
fill the form on `/admin/courses`, then add the Day tabs' lessons and the
Resources tab's files on the follow-up page. The API half — who may POST
`/courses/` and what the student receives — is covered by `test_bootcamps.py`;
the last test here only checks that a bootcamp built by the dashboard is the
thing that API serves.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    BootcampProfile,
    Course,
    CourseInstructor,
    CourseResource,
    Lesson,
    Role,
    User,
)


class BootcampDashboardTests(TestCase):
    def setUp(self):
        self.admin = self.user('admin', 'super_admin')
        self.lead = self.user('lead', 'instructor', verification_status='verified')
        self.coach = self.user('coach', 'instructor', verification_status='verified')
        self.student = self.user('student', 'student')
        self.client.force_login(self.admin)

    def user(self, name, role, **kwargs):
        return User.objects.create_user(
            email=f'{name}@example.com', name=name, role=Role.objects.get(name=role), **kwargs
        )

    def payload(self, **overrides):
        data = {
            'form': 'bootcamp',
            'title': 'ICT & AI BOOTCAMP at Sundarbazar',
            'description': 'Master the foundations of design strategy.',
            'short_description': 'Four days of strategy, brand and delivery.',
            'instructor': self.lead.pk,
            'coaches': [self.coach.pk],
            'venue_name': 'Sundarbazar',
            'days': 4,
            'starts_on': '2026-11-16',
            'ends_on': '2026-11-19',
            'status': 'upcoming',
            'episode_no': 2,
            'quality_label': 'HD',
            'hero_video_url': 'https://cdn.example.com/hero.mp4',
            'hero_poster_url': 'https://cdn.example.com/hero.jpg',
            'thumbnail_url': 'https://cdn.example.com/card.png',
            'level': 'beginner',
            'language': 'English',
            'is_published': 'on',
        }
        data.update(overrides)
        return data

    def create_bootcamp(self, **overrides):
        response = self.client.post(reverse('manage_courses'), self.payload(**overrides))
        return response

    # ── creating ─────────────────────────────────────────────────────────────

    def test_admin_creates_course_profile_and_roster_in_one_post(self):
        response = self.create_bootcamp()

        course = Course.objects.get(title='ICT & AI BOOTCAMP at Sundarbazar')
        self.assertRedirects(
            response, reverse('manage_bootcamp_content', args=[course.pk]), fetch_redirect_response=False
        )
        self.assertEqual(course.course_type, 'bootcamp')
        self.assertEqual(course.instructor, self.lead)
        self.assertTrue(course.is_published)
        # A camp is sold as a seat, not as a course: the design has no price.
        self.assertFalse(course.is_paid)
        self.assertIsNone(course.price)

        profile = course.bootcamp_profile
        self.assertEqual(profile.venue_name, 'Sundarbazar')
        self.assertEqual(profile.days, 4)
        self.assertEqual(profile.starts_on, date(2026, 11, 16))
        self.assertEqual(profile.ends_on, date(2026, 11, 19))
        self.assertEqual(profile.episode_no, 2)
        self.assertEqual(profile.quality_label, 'HD')
        self.assertEqual(profile.hero_video_url, 'https://cdn.example.com/hero.mp4')

        roster = list(course.instructors.order_by('order'))
        self.assertEqual([row.role for row in roster], ['lead', 'coach'])
        self.assertEqual([row.instructor for row in roster], [self.lead, self.coach])

    def test_an_instructor_cannot_reach_the_dashboard_form(self):
        self.client.force_login(self.lead)

        response = self.create_bootcamp()

        # Not `fetch_redirect_response`: the dashboard itself redirects a
        # non-admin again, and the assertion that matters is the destination.
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertFalse(Course.objects.filter(course_type='bootcamp').exists())

    def test_a_student_cannot_reach_the_dashboard_form(self):
        self.client.force_login(self.student)

        response = self.create_bootcamp()

        # Not `fetch_redirect_response`: the dashboard itself redirects a
        # non-admin again, and the assertion that matters is the destination.
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertFalse(Course.objects.filter(course_type='bootcamp').exists())

    def test_end_before_start_is_a_field_error_not_a_500(self):
        response = self.create_bootcamp(ends_on='2026-11-10')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'End date must not precede start date.')
        self.assertFalse(Course.objects.filter(course_type='bootcamp').exists())

    def test_the_lead_cannot_also_be_a_coach(self):
        # `unique_course_instructor` would otherwise 500 after the course exists.
        response = self.create_bootcamp(coaches=[self.lead.pk])

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already on the roster')
        self.assertFalse(Course.objects.filter(course_type='bootcamp').exists())

    def test_the_plain_course_form_still_cannot_make_a_bootcamp(self):
        response = self.client.post(reverse('manage_courses'), {
            'form': 'course',
            'title': 'Sneaky camp',
            'instructor': self.lead.pk,
            'course_type': 'bootcamp',
            'is_published': 'on',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Course.objects.filter(title='Sneaky camp').exists())

    # ── content ──────────────────────────────────────────────────────────────

    def bootcamp(self):
        self.create_bootcamp()
        return Course.objects.get(course_type='bootcamp')

    def content_url(self, course):
        return reverse('manage_bootcamp_content', args=[course.pk])

    def test_lessons_and_files_are_added_from_the_content_page(self):
        course = self.bootcamp()
        lesson_response = self.client.post(self.content_url(course), {
            'form': 'lesson',
            'day_number': 1,
            'section': 'Section 1: Research & Strategy Foundations',
            'title': 'Defining the Product Strategy Grid',
            'duration': '18:45',
            'content_type': 'video',
            'content_url': 'https://cdn.example.com/lesson.mp4',
            'order': 1,
        })
        self.assertRedirects(lesson_response, self.content_url(course), fetch_redirect_response=False)

        lesson = Lesson.objects.get(course=course)
        self.assertEqual(lesson.day_number, 1)
        self.assertEqual(lesson.section, 'Section 1: Research & Strategy Foundations')
        self.assertEqual(lesson.duration_seconds, 1125)

        file_response = self.client.post(self.content_url(course), {
            'form': 'resource',
            'section': 'Section 1: Course Materials',
            'title': 'Product Strategy Grid Template',
            'file_format': 'pdf',
            'file_url': 'https://cdn.example.com/grid.pdf',
            'lesson': lesson.pk,
            'order': 0,
        })
        self.assertRedirects(file_response, self.content_url(course), fetch_redirect_response=False)

        resource = CourseResource.objects.get(course=course)
        self.assertEqual(resource.title, 'Product Strategy Grid Template')
        self.assertEqual(resource.lesson, lesson)

    def test_a_lesson_beyond_the_last_day_is_refused(self):
        course = self.bootcamp()

        response = self.client.post(self.content_url(course), {
            'form': 'lesson',
            'day_number': 9,
            'title': 'Day nine',
            'content_type': 'text',
            'content_text': 'Out of range.',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This bootcamp runs 4 days.')
        self.assertFalse(Lesson.objects.filter(course=course).exists())

    def test_a_video_lesson_needs_a_url(self):
        course = self.bootcamp()

        response = self.client.post(self.content_url(course), {
            'form': 'lesson',
            'day_number': 1,
            'title': 'No file',
            'content_type': 'video',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'A content URL is required for this lesson type.')
        self.assertFalse(Lesson.objects.filter(course=course).exists())

    def test_lessons_can_be_removed(self):
        course = self.bootcamp()
        lesson = Lesson.objects.create(
            course=course, title='Temporary', content_type='text', content_text='x', day_number=1,
        )

        self.client.post(self.content_url(course), {'form': 'delete_lesson', 'lesson_id': lesson.pk})

        self.assertFalse(Lesson.objects.filter(pk=lesson.pk).exists())

    def test_the_content_page_is_admin_only(self):
        course = self.bootcamp()
        self.client.force_login(self.coach)

        response = self.client.get(self.content_url(course))

        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        # And the same for a write, not just the page.
        self.client.post(self.content_url(course), {
            'form': 'lesson', 'day_number': 1, 'title': 'Nope',
            'content_type': 'text', 'content_text': 'x',
        })
        self.assertFalse(Lesson.objects.filter(course=course).exists())

    def test_the_content_page_refuses_a_non_bootcamp(self):
        skill = Course.objects.create(
            title='Python Basics', instructor=self.lead, course_type='skill', is_published=True,
        )

        response = self.client.get(self.content_url(skill))

        self.assertRedirects(response, reverse('manage_courses'))

    def test_details_can_be_edited_after_creation(self):
        # A typo in the venue must be fixable without a second camp — the admin
        # lands on this page right after creating one.
        course = self.bootcamp()

        response = self.client.post(self.content_url(course), {
            **self.payload(),
            'form': 'details',
            'venue_name': 'Palungtar',
            'days': 7,
            'ends_on': '2026-11-22',
        })

        self.assertRedirects(response, self.content_url(course), fetch_redirect_response=False)
        course.refresh_from_db()
        self.assertEqual(course.bootcamp_profile.venue_name, 'Palungtar')
        self.assertEqual(course.bootcamp_profile.days, 7)
        self.assertEqual(
            list(course.instructors.order_by('order').values_list('role', flat=True)),
            ['lead', 'coach'],
        )

    def test_the_run_cannot_be_shortened_under_an_existing_lesson(self):
        # Same rule the API applies: a lesson on day 4 under a 3-day camp would
        # sit on a tab the app never draws.
        course = self.bootcamp()
        Lesson.objects.create(
            course=course, title='Day four', day_number=4,
            content_type='text', content_text='x',
        )

        response = self.client.post(self.content_url(course), {
            **self.payload(),
            'form': 'details',
            'days': 3,
            'ends_on': '2026-11-18',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Existing lessons exceed the proposed days.')
        course.refresh_from_db()
        self.assertEqual(course.bootcamp_profile.days, 4)

    # ── the API serves what the dashboard built ──────────────────────────────

    def test_a_dashboard_bootcamp_reaches_the_student_api(self):
        course = self.bootcamp()
        Lesson.objects.create(
            course=course, title='Defining the Product Strategy Grid', section='Section 1',
            day_number=1, duration_seconds=1125, content_type='video',
            content_url='https://cdn.example.com/lesson.mp4', order=1,
        )
        BootcampProfile.objects.filter(course=course).update(status='ongoing')

        api = APIClient()
        api.force_authenticate(self.student)

        listing = api.get('/api/v1/courses/', {'course_type': 'bootcamp'})
        self.assertEqual(listing.status_code, 200)
        row = next(item for item in listing.data['results'] if item['id'] == course.pk)
        self.assertEqual(row['venue_name'], 'Sundarbazar')
        self.assertEqual(row['days'], 4)
        self.assertEqual(row['status'], 'ongoing')
        self.assertEqual(row['hero_video_url'], 'https://cdn.example.com/hero.mp4')
        self.assertEqual([person['role'] for person in row['instructors']], ['lead', 'coach'])

        detail = api.get(f'/api/v1/courses/{course.pk}/')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['quality_label'], 'HD')
        self.assertEqual(detail.data['episode_no'], 2)

        lessons = api.get('/api/v1/lessons/', {'course': course.pk})
        self.assertEqual(lessons.status_code, 200)
        self.assertEqual(lessons.data[0]['day_number'], 1)
