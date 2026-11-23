"""The bootcamp is admin-only, and the dashboard is where an admin adds one.

These tests cover the path a human actually takes: sign in as an administrator,
fill the form on `/admin/bootcamps/add`, then add the Day tabs' lessons and the
Resources tab's files on the follow-up page. The API half — who may POST
`/courses/` and what the student receives — is covered by `test_bootcamps.py`;
the last test here only checks that a bootcamp built by the dashboard is the
thing that API serves.
"""
from datetime import date

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from tempfile import TemporaryDirectory
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    BootcampProfile,
    Course,
    CourseInstructor,
    CourseResource,
    Lesson,
    Question,
    QuestionOption,
    Quiz,
    QuizAttempt,
    Role,
    StudentAnswer,
    User,
    Enrollment,
)


class BootcampDashboardTestCase(TestCase):
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
        response = self.client.post(reverse('add_bootcamp'), self.payload(**overrides))
        return response

    def bootcamp(self):
        self.create_bootcamp()
        return Course.objects.get(course_type='bootcamp')

    def content_url(self, course):
        return reverse('manage_bootcamp_content', args=[course.pk])


class BootcampDashboardTests(BootcampDashboardTestCase):
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

    def test_management_lists_are_separate_and_navigation_is_available(self):
        camp = self.bootcamp()
        normal = [Course.objects.create(title=f'Normal {kind}', course_type=kind, instructor=self.lead)
                  for kind in ['academic', 'skill', 'premium']]
        response = self.client.get(reverse('manage_courses'))
        self.assertQuerySetEqual(response.context['courses'], [row.pk for row in reversed(normal)], transform=lambda row: row.pk)
        self.assertNotContains(response, camp.title)
        self.assertNotContains(response, 'name="form" value="bootcamp"')
        self.assertContains(response, 'Course Management')
        self.assertContains(response, reverse('manage_bootcamps'))
        Lesson.objects.create(course=camp, title='One', day_number=1, content_type='text')
        Enrollment.objects.create(student=self.student, course=camp, status='active')
        response = self.client.get(reverse('manage_bootcamps'))
        self.assertEqual([row.pk for row in response.context['bootcamps']], [camp.pk])
        row = response.context['bootcamps'][0]
        self.assertEqual((row.instructors_count, row.lessons_count, row.enrolled_count), (2, 1, 1))
        for other in normal:
            self.assertNotContains(response, other.title)
        for label in ['Add Bootcamp', 'Manage Content', 'Manage Instructors', 'Manage Resources', 'Edit / Publish']:
            self.assertContains(response, label)

    def test_normal_course_endpoint_cannot_create_bootcamp_via_old_form(self):
        response = self.client.post(reverse('manage_courses'), self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Course.objects.filter(course_type='bootcamp').exists())

    def test_all_bootcamp_authoring_pages_require_admin(self):
        camp = self.bootcamp()
        urls = [reverse('manage_bootcamps'), reverse('add_bootcamp'), self.content_url(camp),
                reverse('manage_bootcamp_instructors', args=[camp.pk])]
        for user in [self.lead, self.coach, self.student, None]:
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            for url in urls:
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.client.get(url).status_code, 302)
                    self.assertEqual(self.client.post(url, self.payload()).status_code, 302)
        self.assertEqual(Course.objects.filter(course_type='bootcamp').count(), 1)

    def test_dynamic_empty_days_and_lesson_edit(self):
        self.create_bootcamp(days=3)
        camp = Course.objects.get(course_type='bootcamp')
        response = self.client.get(self.content_url(camp))
        self.assertEqual([day for day, _ in response.context['days']], [1, 2, 3])
        self.assertContains(response, 'Day 3')
        data = {'form': 'lesson', 'day_number': 3, 'title': 'Day three', 'content_type': 'text',
                'content_text': 'Introduction', 'order': 2}
        self.assertEqual(self.client.post(self.content_url(camp), data).status_code, 302)
        lesson = Lesson.objects.get(course=camp)
        response = self.client.get(self.content_url(camp), {'lesson_id': lesson.pk})
        self.assertEqual(response.context['lesson_form'].initial['day_number'], 3)
        data.update(lesson_id=lesson.pk, day_number=2, title='Moved lesson', duration='02:10', is_preview='on')
        self.assertEqual(self.client.post(self.content_url(camp), data).status_code, 302)
        lesson.refresh_from_db()
        self.assertEqual((lesson.day_number, lesson.title, lesson.duration_seconds, lesson.order, lesson.is_preview),
                         (2, 'Moved lesson', 130, 2, True))
        data['day_number'] = 4
        response = self.client.post(self.content_url(camp), data)
        self.assertContains(response, 'This bootcamp runs 3 days.')
        lesson.refresh_from_db()
        self.assertEqual(lesson.day_number, 2)

    def test_resource_edit_delete_and_cross_course_lesson_refused(self):
        camp = self.bootcamp()
        other = Course.objects.create(title='Other', instructor=self.lead, course_type='skill')
        other_lesson = Lesson.objects.create(course=other, title='Other lesson', content_type='text')
        lesson = Lesson.objects.create(course=camp, title='Own lesson', day_number=1, content_type='text')
        data = {'form': 'resource', 'title': 'Worksheet', 'file_format': 'pdf',
                'file_url': 'https://example.com/a.pdf', 'lesson': lesson.pk}
        self.assertEqual(self.client.post(self.content_url(camp), data).status_code, 302)
        resource = CourseResource.objects.get(course=camp)
        response = self.client.get(self.content_url(camp), {'resource_id': resource.pk})
        self.assertEqual(response.context['resource_form'].initial['title'], 'Worksheet')
        data.update(resource_id=resource.pk, title='Updated worksheet', order=3)
        self.assertEqual(self.client.post(self.content_url(camp), data).status_code, 302)
        resource.refresh_from_db()
        self.assertEqual((resource.title, resource.order), ('Updated worksheet', 3))
        data['lesson'] = other_lesson.pk
        self.assertEqual(self.client.post(self.content_url(camp), data).status_code, 200)
        resource.refresh_from_db()
        self.assertEqual(resource.lesson, lesson)
        self.client.post(self.content_url(camp), {'form': 'delete_resource', 'resource_id': resource.pk})
        self.assertFalse(CourseResource.objects.filter(pk=resource.pk).exists())

    def test_edits_and_deletes_are_scoped_to_bootcamp(self):
        camp = self.bootcamp()
        other = Course.objects.create(title='Other', instructor=self.lead, course_type='skill')
        lesson = Lesson.objects.create(course=other, title='Protected', content_type='text')
        resource = CourseResource.objects.create(course=other, title='Protected', file_format='pdf', file_url='https://example.com/a.pdf')
        for kind, instance in [('lesson', lesson), ('resource', resource)]:
            self.assertEqual(self.client.get(self.content_url(camp), {f'{kind}_id': instance.pk}).status_code, 404)
            for action in [kind, f'delete_{kind}']:
                self.assertEqual(self.client.post(self.content_url(camp), {'form': action, f'{kind}_id': instance.pk}).status_code, 404)
            self.assertTrue(type(instance).objects.filter(pk=instance.pk).exists())

    def test_dedicated_roster_syncs_lead_and_preserves_guest_role(self):
        camp = self.bootcamp()
        guest = self.user('guest', 'instructor', verification_status='verified')
        CourseInstructor.objects.create(course=camp, instructor=guest, role='guest', order=3)
        url = reverse('manage_bootcamp_instructors', args=[camp.pk])
        response = self.client.post(url, {'instructor': self.coach.pk, 'coaches': [self.lead.pk, guest.pk]})
        self.assertEqual(response.status_code, 302)
        camp.refresh_from_db()
        self.assertEqual(camp.instructor, self.coach)
        self.assertEqual(list(camp.instructors.filter(role='lead').values_list('instructor_id', flat=True)), [self.coach.pk])
        self.assertEqual(camp.instructors.get(instructor=guest).role, 'guest')
        before = list(camp.instructors.values_list('instructor_id', 'role', 'order'))
        response = self.client.post(url, {'instructor': self.lead.pk, 'coaches': [self.lead.pk]})
        self.assertContains(response, 'already on the roster')
        self.assertEqual(list(camp.instructors.values_list('instructor_id', 'role', 'order')), before)
        self.assertEqual(self.client.post(url, {'instructor': self.coach.pk}).status_code, 302)
        self.assertEqual(camp.instructors.count(), 1)

    def test_all_roster_forms_reject_ineligible_instructors(self):
        camp = self.bootcamp()
        unverified = self.user('unverified', 'instructor')
        inactive = self.user('inactive', 'instructor', is_active=False, verification_status='verified')
        original_roster = list(camp.instructors.order_by('pk').values_list('instructor_id', 'role', 'order'))
        for instructor in [unverified, inactive, self.student]:
            for field in ['instructor', 'coaches']:
                for url, form in [
                    (reverse('add_bootcamp'), 'bootcamp'),
                    (self.content_url(camp), 'details'),
                    (reverse('manage_bootcamp_instructors', args=[camp.pk]), 'roster'),
                ]:
                    with self.subTest(instructor=instructor, field=field, form=form):
                        value = [instructor.pk] if field == 'coaches' else instructor.pk
                        response = self.client.post(url, self.payload(**{'form': form, field: value}))
                        self.assertEqual(response.status_code, 200)
                        bound_form = response.context['details_form' if form == 'details' else 'form']
                        self.assertIn(field, bound_form.errors)
                        camp.refresh_from_db()
                        self.assertEqual(camp.instructor_id, self.lead.pk)
                        self.assertEqual(Course.objects.filter(course_type='bootcamp').count(), 1)
                        self.assertEqual(list(camp.instructors.order_by('pk').values_list(
                            'instructor_id', 'role', 'order')), original_roster)

    def test_paid_bootcamp_price_validation_and_publication(self):
        response = self.create_bootcamp(is_paid='on', price='')
        self.assertContains(response, 'A paid bootcamp must have a price')
        self.assertFalse(Course.objects.filter(course_type='bootcamp').exists())
        self.create_bootcamp(is_paid='on', price='500.00', is_published='')
        camp = Course.objects.get(course_type='bootcamp')
        self.assertTrue(camp.is_paid)
        self.assertFalse(camp.is_published)
        response = self.client.post(self.content_url(camp), self.payload(form='details', is_paid='on', price='500.00'))
        self.assertEqual(response.status_code, 302)
        camp.refresh_from_db()
        self.assertTrue(camp.is_published)
        camp.full_clean()

    def test_dashboard_uploads_reuse_course_assets(self):
        camp = self.bootcamp()
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            video = SimpleUploadedFile('intro.mp4', b'video bytes', content_type='video/mp4')
            response = self.client.post(self.content_url(camp), {'form': 'lesson', 'day_number': 1,
                'title': 'Uploaded video', 'content_type': 'video', 'content_file': video})
            self.assertEqual(response.status_code, 302)
            lesson = Lesson.objects.get(course=camp)
            self.assertIn('/course-assets/lesson/', lesson.content_url)
            document = SimpleUploadedFile('worksheet.pdf', b'%PDF-test', content_type='application/pdf')
            response = self.client.post(self.content_url(camp), {'form': 'resource', 'title': 'Uploaded PDF',
                'file_format': 'pdf', 'lesson': lesson.pk, 'resource_file': document})
            self.assertEqual(response.status_code, 302)
            resource = CourseResource.objects.get(course=camp)
            self.assertIn('/course-assets/resource/', resource.file_url)
            self.assertEqual(resource.file_size_bytes, 9)
            invalid = SimpleUploadedFile('bad.html', b'<html>', content_type='text/html')
            response = self.client.post(self.content_url(camp), {'form': 'resource', 'title': 'Rejected',
                'file_format': 'other', 'resource_file': invalid})
            self.assertContains(response, 'This file type is not supported.')
            self.assertEqual(CourseResource.objects.filter(course=camp).count(), 1)


class BootcampQuizDashboardTests(BootcampDashboardTestCase):
    """An admin attaches a quiz to a camp section from the content page.

    The app places it by exact match on `Lesson.section` and reads it through
    the ordinary course quiz endpoints, which is what the last check covers.
    """
    SECTION = 'Section 1: Research & Strategy Foundations'

    def setUp(self):
        super().setUp()
        self.camp = self.bootcamp()
        self.url = self.content_url(self.camp)
        Lesson.objects.create(
            course=self.camp, title='Strategy grid', section=self.SECTION, day_number=1,
            content_type='text', content_text='x',
        )

    def quiz_data(self, **overrides):
        data = {'form': 'quiz', 'section': self.SECTION, 'title': 'Strategy check', 'description': '',
                'pass_percentage': 60, 'max_attempts': 2, 'time_limit': '5:00'}
        data.update(overrides)
        return data

    def question_data(self, quiz, **overrides):
        data = {'form': 'question', 'quiz_id': quiz.pk, 'text': 'What does the grid map?',
                'option_1': 'Risk', 'option_2': 'Effort against impact', 'option_3': '', 'option_4': '',
                'correct_option': 'option_2', 'hint': 'Two axes.', 'explanation': 'It plots effort and impact.',
                'marks': 1, 'points': 5}
        data.update(overrides)
        return data

    def quiz(self, published=False, **fields):
        quiz = Quiz.objects.create(course=self.camp, title='Strategy check', section=self.SECTION, **fields)
        question = Question.objects.create(quiz=quiz, text='Q1', order=1)
        QuestionOption.objects.create(question=question, text='Right', is_correct=True)
        QuestionOption.objects.create(question=question, text='Wrong')
        if published:
            Quiz.objects.filter(pk=quiz.pk).update(is_published=True)
            quiz.refresh_from_db()
        return quiz

    def test_admin_builds_and_publishes_a_quiz_the_student_receives(self):
        self.assertIn((self.SECTION, self.SECTION), self.client.get(self.url).context['quiz_form'].fields['section'].choices)

        response = self.client.post(self.url, self.quiz_data())
        quiz = Quiz.objects.get(course=self.camp)
        self.assertRedirects(response, f'{self.url}?quiz_id={quiz.pk}#questions', fetch_redirect_response=False)
        self.assertEqual((quiz.section, quiz.time_limit_seconds, quiz.is_published), (self.SECTION, 300, False))

        response = self.client.post(self.url, self.question_data(quiz))
        self.assertEqual(response.status_code, 302)
        question = quiz.questions.get()
        self.assertEqual((question.hint, question.points, question.order), ('Two axes.', 5, 1))
        self.assertEqual(list(question.options.order_by('pk').values_list('text', 'is_correct')),
                         [('Risk', False), ('Effort against impact', True)])

        self.client.post(self.url, self.quiz_data(quiz_id=quiz.pk, is_published='on'))
        quiz.refresh_from_db()
        self.assertTrue(quiz.is_published)

        Enrollment.objects.create(student=self.student, course=self.camp, status='active')
        api = APIClient()
        api.force_authenticate(self.student)
        listing = api.get(f'/api/v1/courses/{self.camp.pk}/quizzes/')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([(row['id'], row['section'], row['time_limit_seconds']) for row in listing.data],
                         [(quiz.pk, self.SECTION, 300)])
        self.assertEqual(api.post(f'/api/v1/student/quizzes/{quiz.pk}/start/').status_code, 201)

    def test_publishing_follows_the_api_rules(self):
        response = self.client.post(self.url, self.quiz_data(is_published='on'))
        self.assertContains(response, 'Create the quiz as draft')
        self.assertFalse(Quiz.objects.exists())

        empty = Quiz.objects.create(course=self.camp, title='Empty', section=self.SECTION)
        response = self.client.post(self.url, self.quiz_data(quiz_id=empty.pk, is_published='on'))
        self.assertContains(response, 'at least one question')
        empty.refresh_from_db()
        self.assertFalse(empty.is_published)

        response = self.client.post(self.url, self.quiz_data(quiz_id=empty.pk, time_limit='0:05'))
        self.assertContains(response, 'Quiz time must be between 15 seconds and 60 minutes.')

    def test_section_must_be_one_the_lessons_use_and_hold_one_quiz(self):
        response = self.client.post(self.url, self.quiz_data(section='Section 1: Research & Strategy'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('section', response.context['quiz_form'].errors)
        self.assertFalse(Quiz.objects.exists())

        self.quiz()
        response = self.client.post(self.url, self.quiz_data(title='Second'))
        self.assertContains(response, 'This module already has a quiz.')
        self.assertEqual(Quiz.objects.count(), 1)

        # A quiz on the lessons with no section is the blank choice.
        self.assertEqual(self.client.post(self.url, self.quiz_data(section='', title='Loose')).status_code, 302)
        self.assertIsNone(Quiz.objects.get(title='Loose').section)

    def test_question_needs_two_options_and_a_filled_correct_one(self):
        quiz = self.quiz()
        response = self.client.post(self.url, self.question_data(quiz, option_2='', correct_option='option_1'))
        self.assertContains(response, 'Give at least two options.')
        response = self.client.post(self.url, self.question_data(quiz, correct_option='option_3'))
        self.assertContains(response, 'The correct option is blank.')
        self.assertEqual(quiz.questions.count(), 1)

    def test_editing_a_question_keeps_option_rows_and_drops_blanked_ones(self):
        quiz = self.quiz()
        question = quiz.questions.get()
        QuestionOption.objects.create(question=question, text='Third')
        first, second, third = question.options.order_by('pk')

        self.client.post(self.url, self.question_data(
            quiz, question_id=question.pk, text='Edited', option_1='Right!', option_2='Wrong', option_3='',
            correct_option='option_1', order=4))

        question.refresh_from_db()
        self.assertEqual((question.text, question.order), ('Edited', 4))
        self.assertEqual(list(question.options.order_by('pk').values_list('pk', 'text', 'is_correct')),
                         [(first.pk, 'Right!', True), (second.pk, 'Wrong', False)])
        self.assertFalse(QuestionOption.objects.filter(pk=third.pk).exists())

    def test_questions_lock_once_a_student_has_finished_the_quiz(self):
        quiz = self.quiz(published=True)
        QuizAttempt.objects.create(student=self.student, quiz=quiz, completed_at=timezone.now())
        question = quiz.questions.get()

        self.assertContains(self.client.get(self.url, {'quiz_id': quiz.pk}), 'its questions are locked')
        self.client.post(self.url, self.question_data(quiz))
        self.client.post(self.url, self.question_data(quiz, question_id=question.pk, text='Changed'))
        self.client.post(self.url, {'form': 'delete_question', 'quiz_id': quiz.pk, 'question_id': question.pk})

        self.assertEqual(list(quiz.questions.values_list('text', flat=True)), ['Q1'])
        # Settings that do not rewrite answers stay editable.
        self.client.post(self.url, self.quiz_data(quiz_id=quiz.pk, max_attempts=3, is_published='on'))
        quiz.refresh_from_db()
        self.assertEqual(quiz.max_attempts, 3)

    def test_an_answered_option_in_an_open_attempt_is_not_deleted(self):
        quiz = self.quiz(published=True)
        question = quiz.questions.get()
        wrong = question.options.get(is_correct=False)
        attempt = QuizAttempt.objects.create(student=self.student, quiz=quiz)
        StudentAnswer.objects.create(attempt=attempt, question=question, selected_option=wrong)
        Question.objects.create(quiz=quiz, text='Spare', order=2)

        response = self.client.post(self.url, {'form': 'delete_question', 'quiz_id': quiz.pk, 'question_id': question.pk}, follow=True)

        self.assertContains(response, 'part-way through this quiz')
        self.assertTrue(Question.objects.filter(pk=question.pk).exists())

    def test_last_question_of_a_published_quiz_stays(self):
        quiz = self.quiz(published=True)
        question = quiz.questions.get()

        response = self.client.post(self.url, {'form': 'delete_question', 'quiz_id': quiz.pk, 'question_id': question.pk}, follow=True)

        self.assertContains(response, 'Unpublish it first.')
        self.assertTrue(Question.objects.filter(pk=question.pk).exists())

    def test_quiz_can_be_removed(self):
        quiz = self.quiz()
        self.client.post(self.url, {'form': 'delete_quiz', 'quiz_id': quiz.pk})
        self.assertFalse(Quiz.objects.filter(pk=quiz.pk).exists())

    def test_quiz_edits_are_scoped_to_the_bootcamp_and_admin_only(self):
        other = Course.objects.create(title='Other', instructor=self.lead, course_type='skill')
        foreign = Quiz.objects.create(course=other, title='Protected')
        foreign_question = Question.objects.create(quiz=foreign, text='Protected')
        own = self.quiz()
        for params in [{'quiz_id': foreign.pk}, {'quiz_id': own.pk, 'question_id': foreign_question.pk},
                       {'question_id': own.questions.get().pk}]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 404)
                for action in ['quiz', 'delete_quiz', 'question', 'delete_question']:
                    self.assertEqual(self.client.post(self.url, {'form': action, **params}).status_code, 404)
        self.assertTrue(Quiz.objects.filter(pk=foreign.pk).exists())
        self.assertTrue(Question.objects.filter(pk=foreign_question.pk).exists())

        self.client.force_login(self.lead)
        response = self.client.post(self.url, self.quiz_data(section='', title='Instructor quiz'))
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.assertFalse(Quiz.objects.filter(title='Instructor quiz').exists())
