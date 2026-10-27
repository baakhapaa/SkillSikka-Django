from datetime import date
from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import connection, IntegrityError, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient
from core.models import (Course, BootcampProfile, CourseInstructor, BootcampResource, BootcampDiscussion,
    DiscussionLike, Enrollment, Lesson, LessonProgress, Role, User, StudentProfile, Grade, Payment, Certificate)


class BootcampTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = self.user('admin', 'super_admin')
        self.lead = self.user('lead', 'instructor', verification_status='verified')
        self.coach = self.user('coach', 'instructor', verification_status='verified')
        self.student = self.user('student', 'student')
        self.other = self.user('other', 'student')
        self.course = self.bootcamp()
        self.lesson = self.lesson_for(self.course, 1)
        self.client.force_authenticate(self.student)

    def user(self, name, role, **kwargs):
        return User.objects.create_user(email=f'{name}@example.com', name=name, role=Role.objects.get(name=role), **kwargs)

    def bootcamp(self, **kwargs):
        course = Course.objects.create(title='ICT & AI Bootcamp', instructor=self.lead, course_type='bootcamp', is_published=kwargs.pop('is_published', True), **kwargs)
        BootcampProfile.objects.create(course=course, venue_name='Sundarbazar', days=4, starts_on=date(2026, 9, 21), ends_on=date(2026, 9, 24), status='completed')
        CourseInstructor.objects.create(course=course, instructor=self.lead, role='lead')
        CourseInstructor.objects.create(course=course, instructor=self.coach, role='coach', order=1)
        return course

    def lesson_for(self, course, order, **kwargs):
        return Lesson.objects.create(course=course, order=order, title=f'Lesson {order}', content_type='text', content_text='Protected',
            section='Foundations', duration_seconds=300, day_number=1, **kwargs)

    def url(self, suffix='', course=None):
        return f'/api/v1/courses/{(course or self.course).pk}/{suffix}'

    def enroll(self, status='active', user=None):
        return Enrollment.objects.update_or_create(student=user or self.student, course=self.course, defaults={'status': status})[0]

    def payload(self):
        return {'title': 'New bootcamp', 'course_type': 'bootcamp', 'lead_instructor_id': self.lead.pk,
            'instructors': [{'instructor': self.lead.pk, 'role': 'lead', 'order': 0}, {'instructor': self.coach.pk, 'role': 'coach', 'order': 1}],
            'bootcamp_profile': {'venue_name': 'Palungtar', 'days': 7, 'starts_on': '2026-11-16', 'ends_on': '2026-11-22'}, 'is_published': True}

    def post_course(self, payload=None):
        self.client.force_authenticate(self.admin)
        return self.client.post('/api/v1/courses/', self.payload() if payload is None else payload, format='json')

    def error(self, response, code, status=400):
        self.assertEqual(response.status_code, status, response.data)
        self.assertEqual(response.data['code'], code)

    def discussion(self, **kwargs):
        return BootcampDiscussion.objects.create(course=kwargs.pop('course', self.course), author=kwargs.pop('author', self.student), body=kwargs.pop('body', 'How can we check AI answers?'), **kwargs)

    def test_create_admin_owner_and_roster(self):
        response = self.post_course()
        self.assertEqual(response.status_code, 201, response.data)
        course = Course.objects.get(pk=response.data['id'])
        self.assertEqual(course.instructor, self.lead)
        self.assertEqual(course.instructors.get(role='lead').instructor, self.lead)
        self.assertNotIn('lead_instructor_id', response.data)
        self.assertTrue(course.is_published)
        self.assertIsNone(course.subject); self.assertIsNone(course.grade)
        self.assertEqual(response.data['venue_name'], 'Palungtar')

    def test_create_non_admin(self):
        for user in [self.lead, self.coach, self.student]:
            self.client.force_authenticate(user)
            self.error(self.client.post('/api/v1/courses/', self.payload(), format='json'), 'ADMIN_ONLY', 403)

    def test_lead_required(self):
        data = self.payload(); del data['lead_instructor_id']
        self.error(self.post_course(data), 'LEAD_INSTRUCTOR_REQUIRED')
        data['lead_instructor_id'] = None
        self.error(self.post_course(data), 'LEAD_INSTRUCTOR_REQUIRED')

    def test_lead_roster_consistency(self):
        for roster in [None, [], [{'instructor': self.coach.pk, 'role': 'lead'}],
                [{'instructor': self.lead.pk, 'role': 'lead'}, {'instructor': self.coach.pk, 'role': 'lead'}]]:
            data = self.payload()
            if roster is None: del data['instructors']
            else: data['instructors'] = roster
            self.error(self.post_course(data), 'LEAD_INSTRUCTOR_NOT_IN_ROSTER')

    def test_profile_required(self):
        data = self.payload(); del data['bootcamp_profile']
        self.assertEqual(self.post_course(data).status_code, 400)

    def test_invalid_instructors(self):
        unverified = self.user('unverified', 'instructor')
        inactive = self.user('inactive', 'instructor', verification_status='verified', is_active=False)
        for pk in [self.admin.pk, self.student.pk, unverified.pk, inactive.pk, 999999]:
            data = self.payload(); data['lead_instructor_id'] = pk
            self.assertEqual(self.post_course(data).status_code, 400)
        data = self.payload(); data['instructors'][1]['instructor'] = self.student.pk
        self.assertEqual(self.post_course(data).status_code, 400)

    def test_duplicate_roster(self):
        data = self.payload(); data['instructors'].append(data['instructors'][0])
        self.assertEqual(self.post_course(data).status_code, 400)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseInstructor.objects.create(course=self.course, instructor=self.lead, role='guest')

    def test_invalid_profile_no_partial_create(self):
        before = (Course.objects.count(), BootcampProfile.objects.count(), CourseInstructor.objects.count())
        for changes in [{'days': 0}, {'days': -1}, {'ends_on': '2020-01-01'}, {'venue_name': ''}, {'starts_on': None}]:
            data = self.payload(); data['bootcamp_profile'].update(changes)
            self.assertEqual(self.post_course(data).status_code, 400)
            self.assertEqual((Course.objects.count(), BootcampProfile.objects.count(), CourseInstructor.objects.count()), before)

    def test_database_failure_rolls_back(self):
        before = Course.objects.count()
        with patch('core.serializers.CourseInstructor.objects.bulk_create', side_effect=IntegrityError('fixture failure')):
            with self.assertRaises(IntegrityError): self.post_course()
        self.assertEqual(Course.objects.count(), before)
        self.assertFalse(BootcampProfile.objects.filter(venue_name='Palungtar').exists())

    def test_profile_model_validation(self):
        profile = self.course.bootcamp_profile
        for field, value in [('days', 0), ('ends_on', date(2025, 1, 1)), ('venue_name', '')]:
            old = getattr(profile, field); setattr(profile, field, value)
            with self.assertRaises(ValidationError): profile.full_clean()
            setattr(profile, field, old)
        profile.course = Course.objects.create(title='Skill', instructor=self.lead, course_type='skill')
        with self.assertRaises(ValidationError): profile.full_clean()

    def test_model_subresources_bootcamp_only(self):
        skill = Course.objects.create(title='Skill', instructor=self.lead, course_type='skill')
        for obj in [BootcampResource(course=skill, title='Guide', file_format='pdf', file_url='https://example.com/a.pdf'),
                    BootcampDiscussion(course=skill, author=self.student, body='Hello')]:
            with self.assertRaises(ValidationError): obj.full_clean()

    def test_patch_without_resending_lead(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(self.url(), {'title': 'Updated', 'bootcamp_profile': {'ends_on': '2026-09-25'}}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['ends_on'], '2026-09-25')
        self.assertEqual(response.data['instructor'], self.lead.pk)

    def test_patch_lead_consistency(self):
        self.client.force_authenticate(self.admin)
        self.error(self.client.patch(self.url(), {'lead_instructor_id': self.coach.pk}, format='json'), 'LEAD_INSTRUCTOR_NOT_IN_ROSTER')
        response = self.client.patch(self.url(), {'lead_instructor_id': self.coach.pk, 'instructors': [
            {'instructor': self.coach.pk, 'role': 'lead'}, {'instructor': self.lead.pk, 'role': 'guest'}]}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.course.refresh_from_db(); self.assertEqual(self.course.instructor, self.coach)

    def test_invalid_patch_preserves_state(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(self.url(), {'title': 'Bad', 'bootcamp_profile': {'starts_on': '2030-01-01'}}, format='json')
        self.assertEqual(response.status_code, 400)
        self.course.refresh_from_db(); self.assertEqual(self.course.title, 'ICT & AI Bootcamp')

    def test_type_conversion_rejected(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(self.url(), {'course_type': 'skill'}, format='json').status_code, 400)

    def test_course_write_guards_published_and_draft(self):
        for published in [True, False]:
            self.course.is_published = published; self.course.save()
            for user in [self.lead, self.coach, self.student]:
                self.client.force_authenticate(user)
                self.error(self.client.patch(self.url(), {'title': 'Bad'}, format='json'), 'ADMIN_ONLY', 403)
                self.error(self.client.delete(self.url()), 'ADMIN_ONLY', 403)

    def test_admin_publish_unpublish_delete(self):
        self.client.force_authenticate(self.admin)
        for value in [False, True]:
            response = self.client.patch(self.url(), {'is_published': value}, format='json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['is_published'], value)
        self.assertEqual(self.client.delete(self.url()).status_code, 204)

    def test_paid_price_validation(self):
        for price in [None, 0, -1]:
            data = self.payload(); data.update(is_paid=True, price=price)
            self.assertEqual(self.post_course(data).status_code, 400)
        data = self.payload(); data.update(is_paid=True, price='100.00')
        self.assertEqual(self.post_course(data).status_code, 201)

    def test_list_detail_contract(self):
        self.enroll()
        BootcampResource.objects.create(course=self.course, title='Guide', file_format='pdf', file_url='https://example.com/a.pdf')
        self.discussion(); self.discussion(is_hidden=True)
        data = self.client.get('/api/v1/courses/', {'course_type': 'bootcamp'}).data
        self.assertEqual(set(data), {'count', 'next', 'previous', 'results'})
        row = data['results'][0]
        expected = {'id', 'title', 'course_type', 'description', 'short_description', 'thumbnail_url', 'hero_video_url', 'hero_poster_url',
            'venue_name', 'days', 'starts_on', 'ends_on', 'status', 'episode_no', 'quality_label', 'view_count', 'students_enrolled',
            'lessons_count', 'total_duration_seconds', 'is_enrolled', 'average_rating', 'review_count', 'instructor', 'instructor_name',
            'instructors', 'is_paid', 'price', 'is_published', 'created_at', 'updated_at'}
        self.assertTrue(expected <= set(row), expected - set(row))
        self.assertEqual((row['students_enrolled'], row['lessons_count'], row['total_duration_seconds']), (1, 1, 300))
        self.assertTrue(row['is_enrolled']); self.assertEqual(row['instructors'][0]['id'], self.lead.pk)
        detail = self.client.get(self.url()).data
        self.assertEqual((detail['resources_count'], detail['discussions_count']), (1, 1))

    def test_admin_lesson_crud(self):
        self.client.force_authenticate(self.admin)
        data = {'course': self.course.pk, 'title': 'Demo', 'content_type': 'text', 'content_text': 'Hello', 'day_number': 4,
            'section': 'Projects', 'duration_seconds': 252, 'is_preview': True}
        response = self.client.post('/api/v1/lessons/', data, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data['day_number'], response.data['section'], response.data['duration_seconds'], response.data['is_preview']), (4, 'Projects', 252, True))
        url = f'/api/v1/lessons/{response.data["id"]}/'
        self.assertEqual(self.client.patch(url, {'day_number': 3}, format='json').status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_lesson_author_guards(self):
        for user in [self.lead, self.coach, self.student]:
            self.client.force_authenticate(user)
            data = {'course': self.course.pk, 'title': 'Bad', 'content_type': 'text', 'content_text': 'Bad'}
            self.error(self.client.post('/api/v1/lessons/', data, format='json'), 'ADMIN_ONLY', 403)
            self.error(self.client.patch(f'/api/v1/lessons/{self.lesson.pk}/', {'title': 'Bad'}, format='json'), 'ADMIN_ONLY', 403)
            self.error(self.client.delete(f'/api/v1/lessons/{self.lesson.pk}/'), 'ADMIN_ONLY', 403)

    def test_lesson_move_guard(self):
        skill = Course.objects.create(title='Skill', course_type='skill', instructor=self.lead, is_published=True)
        lesson = self.lesson_for(skill, 1)
        self.client.force_authenticate(self.lead)
        self.error(self.client.patch(f'/api/v1/lessons/{lesson.pk}/', {'course': self.course.pk}, format='json'), 'ADMIN_ONLY', 403)

    def test_lesson_day_range_and_profile_shrink(self):
        self.client.force_authenticate(self.admin)
        for day in [0, -1, 5]:
            self.assertEqual(self.client.patch(f'/api/v1/lessons/{self.lesson.pk}/', {'day_number': day}, format='json').status_code, 400)
        self.lesson.day_number = 4; self.lesson.save()
        self.assertEqual(self.client.patch(self.url(), {'bootcamp_profile': {'days': 3}}, format='json').status_code, 400)
        self.assertEqual(len(self.client.get('/api/v1/lessons/', {'course': self.course.pk, 'day_number': 4}).data), 1)

    def test_enrollment_free_duplicate_paid(self):
        response = self.client.post(self.url('enroll/'))
        self.assertEqual(response.status_code, 201, response.data); self.assertEqual(response.data['status'], 'active')
        self.error(self.client.post(self.url('enroll/')), 'ALREADY_ENROLLED')
        paid = self.bootcamp(is_paid=True, price='100.00')
        response = self.client.post(self.url('enroll/', paid))
        self.assertEqual(response.status_code, 201); self.assertEqual(response.data['status'], 'pending_payment')
        self.assertEqual(Payment.objects.count(), 0)

    def test_enrollment_academic_skill_unpublished(self):
        for kind, status in [('academic', 400), ('skill', 201)]:
            course = Course.objects.create(title=kind, course_type=kind, instructor=self.lead, is_published=True)
            response = self.client.post(self.url('enroll/', course))
            self.assertEqual(response.status_code, status)
            if kind == 'academic': self.assertEqual(response.data['code'], 'COURSE_NOT_ENROLLABLE')
        self.course.is_published = False; self.course.save()
        self.error(self.client.post(self.url('enroll/')), 'COURSE_NOT_PUBLISHED')

    def test_paywall_all_states(self):
        self.lesson_for(self.course, 2, is_preview=True)
        for state in [None, 'active', 'completed', 'pending_payment', 'cancelled']:
            Enrollment.objects.filter(course=self.course).delete()
            if state: self.enroll(state)
            rows = self.client.get('/api/v1/lessons/', {'course': self.course.pk}).data
            self.assertEqual(rows[0]['content_text'], 'Protected' if state in ['active', 'completed'] else None)
            self.assertEqual(rows[1]['content_text'], 'Protected')
            self.assertEqual(self.client.get(f'/api/v1/lessons/{self.lesson.pk}/').data['content_text'], rows[0]['content_text'])
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(f'/api/v1/lessons/{self.lesson.pk}/').data['content_text'], 'Protected')

    def test_completion_scoped_constant_queries(self):
        LessonProgress.objects.create(student=self.student, lesson=self.lesson, is_completed=True)
        with CaptureQueriesContext(connection) as one:
            response = self.client.get('/api/v1/lessons/', {'course': self.course.pk})
        one_count = len(one)
        self.assertGreater(one_count, 0)
        self.assertTrue(response.data[0]['is_completed'])
        for i in range(2, 21): self.lesson_for(self.course, i)
        with CaptureQueriesContext(connection) as twenty:
            response = self.client.get('/api/v1/lessons/', {'course': self.course.pk})
        twenty_count = len(twenty)
        self.assertEqual(one_count, twenty_count)
        self.assertTrue(all(not row['is_completed'] for row in response.data[1:]))
        self.client.force_authenticate(self.other)
        self.assertFalse(self.client.get('/api/v1/lessons/', {'course': self.course.pk}).data[0]['is_completed'])
        print(f'PERF curriculum 1/20 lessons: {one_count}/{twenty_count} queries')

    def test_resources_access_states(self):
        for state in [None, 'pending_payment', 'cancelled', 'active', 'completed']:
            Enrollment.objects.filter(course=self.course).delete()
            if state: self.enroll(state)
            response = self.client.get(self.url('resources/'))
            if state in ['active', 'completed']:
                self.assertEqual(response.status_code, 200); self.assertIsInstance(response.data, list)
            else: self.error(response, 'NOT_ENROLLED', 403)
        for user in [self.admin, self.coach]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url('resources/')).status_code, 200)

    def test_resources_crud_formats_order_wrong_course(self):
        self.client.force_authenticate(self.admin)
        ids = []
        for i, fmt in enumerate(['pdf', 'doc', 'docx', 'xls', 'xlsx', 'figma', 'svg', 'zip', 'link', 'other']):
            response = self.client.post(self.url('resources/'), {'title': fmt, 'file_format': fmt, 'file_url': 'https://example.com/demo', 'order': 10-i}, format='json')
            self.assertEqual(response.status_code, 201, response.data); ids.append(response.data['id'])
        self.assertEqual([r['order'] for r in self.client.get(self.url('resources/')).data], list(range(1, 11)))
        url = self.url(f'resources/{ids[0]}/')
        self.assertEqual(self.client.patch(url, {'title': 'Updated'}, format='json').status_code, 200)
        self.assertEqual(self.client.patch(url, {'file_format': 'exe'}, format='json').status_code, 400)
        second = self.bootcamp()
        self.assertEqual(self.client.patch(self.url(f'resources/{ids[0]}/', second), {'title': 'Bad'}, format='json').status_code, 404)
        self.assertEqual(self.client.delete(self.url(f'resources/{ids[0]}/', second)).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_resource_authoring_admin_only(self):
        resource = BootcampResource.objects.create(course=self.course, title='Guide', file_format='pdf', file_url='https://example.com/a')
        for user in [self.student, self.lead, self.coach]:
            self.client.force_authenticate(user)
            self.error(self.client.post(self.url('resources/'), {}, format='json'), 'ADMIN_ONLY', 403)
            self.error(self.client.patch(self.url(f'resources/{resource.pk}/'), {'title': 'Bad'}, format='json'), 'ADMIN_ONLY', 403)
            self.error(self.client.delete(self.url(f'resources/{resource.pk}/')), 'ADMIN_ONLY', 403)

    def test_discussion_read_and_post_access(self):
        self.discussion()
        response = self.client.get(self.url('discussions/'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'count', 'next', 'previous', 'results'})
        self.error(self.client.post(self.url('discussions/'), {'body': 'Hello'}, format='json'), 'NOT_ENROLLED', 403)
        self.enroll()
        self.assertEqual(self.client.post(self.url('discussions/'), {'body': 'Hello'}, format='json').status_code, 201)
        for user in [self.coach, self.admin]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.post(self.url('discussions/'), {'body': 'Hello'}, format='json').status_code, 201)

    def test_discussion_body_errors(self):
        self.enroll()
        for body in [None, '', '   ']:
            data = {} if body is None else {'body': body}
            self.error(self.client.post(self.url('discussions/'), data, format='json'), 'BODY_REQUIRED')
        self.error(self.client.post(self.url('discussions/'), {'body': 'a'*2001}, format='json'), 'BODY_TOO_LONG')
        self.assertEqual(self.client.post(self.url('discussions/'), {'body': 'a'*2000}, format='json').status_code, 201)

    def test_replies_same_course_one_level(self):
        self.enroll(); thread = self.discussion()
        response = self.client.post(self.url('discussions/'), {'body': 'Reply', 'parent': thread.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.error(self.client.post(self.url('discussions/'), {'body': 'Deep', 'parent': response.data['id']}, format='json'), 'DISCUSSION_NOT_FOUND')
        other = self.discussion(course=self.bootcamp())
        self.error(self.client.post(self.url('discussions/'), {'body': 'Wrong', 'parent': other.pk}, format='json'), 'DISCUSSION_NOT_FOUND', 404)

    def test_discussion_scoped_state_author_and_replies(self):
        StudentProfile.objects.create(user=self.student, grade=Grade.objects.first())
        thread = self.discussion(); self.discussion(parent=thread, author=self.coach, body='Reply')
        self.discussion(parent=thread, is_hidden=True, body='Hidden')
        DiscussionLike.objects.create(discussion=thread, user=self.student)
        row = self.client.get(self.url('discussions/')).data['results'][0]
        self.assertEqual((row['likes_count'], row['replies_count'], len(row['replies'])), (1, 1, 1))
        self.assertTrue(row['is_liked']); self.assertTrue(row['is_mine'])
        self.assertIn('Grade', row['author']['role_label']); self.assertNotIn('Grade Grade', row['author']['role_label'])
        self.assertEqual(row['replies'][0]['author']['role_label'], 'Instructor')
        self.client.force_authenticate(self.other)
        row = self.client.get(self.url('discussions/')).data['results'][0]
        self.assertFalse(row['is_liked']); self.assertFalse(row['is_mine'])
        self.assertEqual(row['author']['id'], self.student.pk)

    def test_hidden_threads_not_interactable(self):
        self.enroll(); thread = self.discussion(is_hidden=True)
        reply = self.discussion(parent=thread, body='Visible child')
        self.assertEqual(self.client.get(self.url('discussions/')).data['count'], 0)
        for discussion in [thread, reply]:
            self.error(self.client.post(self.url(f'discussions/{discussion.pk}/like/')), 'DISCUSSION_NOT_FOUND', 404)
            self.error(self.client.delete(self.url(f'discussions/{discussion.pk}/')), 'DISCUSSION_NOT_FOUND', 404)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url('discussions/')).data['count'], 1)

    def test_discussion_pagination_order(self):
        first = self.discussion(body='First'); last = self.discussion(body='Last')
        DiscussionLike.objects.create(discussion=first, user=self.other)
        for ordering, expected in [('created_at', first), ('-created_at', last), ('-likes_count', first), ('invalid', last)]:
            response = self.client.get(self.url('discussions/'), {'ordering': ordering, 'page_size': 1})
            self.assertEqual(response.data['results'][0]['id'], expected.pk)
            self.assertIsNotNone(response.data['next'])
            self.assertEqual(len(self.client.get(self.url('discussions/'), {'page_size': 1, 'page': 2}).data['results']), 1)

    def test_inline_reply_cap_constant_queries(self):
        thread = self.discussion(); self.discussion(parent=thread, body='First reply')
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url('discussions/'))
        small_count = len(small)
        self.assertGreater(small_count, 0)
        for i in range(54): self.discussion(parent=thread, body=f'Reply {i}', author=self.coach)
        for i in range(19):
            top = self.discussion(body=f'Thread {i}'); self.discussion(parent=top, body='One reply')
        with CaptureQueriesContext(connection) as large:
            response = self.client.get(self.url('discussions/'))
        large_count = len(large)
        self.assertEqual(small_count, large_count)
        row = next(row for row in response.data['results'] if row['id'] == thread.pk)
        self.assertEqual(row['replies_count'], 55); self.assertEqual(len(row['replies']), 50)
        print(f'PERF discussions 1/20 threads: {small_count}/{large_count} queries')

    def test_likes_idempotent_wrong_course(self):
        self.enroll(); thread = self.discussion(); url = self.url(f'discussions/{thread.pk}/like/')
        for _ in range(2):
            response = self.client.post(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, {'discussion_id': thread.pk, 'is_liked': True, 'likes_count': 1})
            self.assertEqual(DiscussionLike.objects.count(), 1)
        for _ in range(2):
            response = self.client.delete(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data['likes_count'], 0); self.assertFalse(response.data['is_liked'])
        other_course = self.bootcamp(); Enrollment.objects.create(course=other_course, student=self.student)
        self.error(self.client.post(self.url(f'discussions/{thread.pk}/like/', other_course)), 'DISCUSSION_NOT_FOUND', 404)

    def test_delete_author_admin_and_cascade(self):
        thread = self.discussion(); reply = self.discussion(parent=thread, author=self.coach)
        DiscussionLike.objects.create(discussion=reply, user=self.coach)
        for user in [self.other, self.lead, self.coach]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.delete(self.url(f'discussions/{thread.pk}/')).status_code, 403)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.delete(self.url(f'discussions/{thread.pk}/')).status_code, 204)
        self.assertFalse(BootcampDiscussion.objects.filter(pk=reply.pk).exists()); self.assertEqual(DiscussionLike.objects.count(), 0)
        own = self.discussion(author=self.coach)
        self.client.force_authenticate(self.coach)
        self.assertEqual(self.client.delete(self.url(f'discussions/{own.pk}/')).status_code, 204)
        any_post = self.discussion(); self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.delete(self.url(f'discussions/{any_post.pk}/')).status_code, 204)

    def test_moderation_and_no_body_edit(self):
        thread = self.discussion(); url = self.url(f'discussions/{thread.pk}/')
        for user in [self.student, self.coach]:
            self.client.force_authenticate(user)
            self.error(self.client.patch(url, {'is_hidden': True}, format='json'), 'ADMIN_ONLY', 403)
        self.client.force_authenticate(self.admin)
        for value in [True, False]:
            response = self.client.patch(url, {'is_hidden': value}, format='json')
            self.assertEqual(response.status_code, 200); self.assertEqual(response.data['is_hidden'], value)
        self.assertEqual(self.client.patch(url, {'body': 'Changed', 'is_hidden': False}, format='json').status_code, 400)
        thread.refresh_from_db(); self.assertEqual(thread.body, 'How can we check AI answers?')

    def test_subresources_require_authentication(self):
        self.client.force_authenticate(None)
        for suffix in ['resources/', 'discussions/']:
            self.assertEqual(self.client.get(self.url(suffix)).status_code, 401)

    def test_home_limit_publication_order(self):
        for i in range(8):
            course = self.bootcamp(is_published=i != 7)
            BootcampProfile.objects.filter(course=course).update(starts_on=date(2026, 9, i+1))
        data = self.client.get('/api/v1/home/').data
        self.assertTrue({'featured_courses', 'recommended_courses', 'skill_courses', 'events', 'advertisements', 'top_instructors', 'bootcamps'} <= set(data))
        self.assertEqual(len(data['bootcamps']), 6)
        self.assertTrue(all(row['is_published'] for row in data['bootcamps']))
        self.assertEqual([r['starts_on'] for r in data['bootcamps']], sorted([r['starts_on'] for r in data['bootcamps']], reverse=True))

    def test_catalogue_detail_home_constant_queries(self):
        def capture(url, params=None):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(url, params or {}); self.assertEqual(response.status_code, 200, response.data)
            return len(queries)
        capture('/api/v1/home/')
        urls = [('/api/v1/courses/', {'course_type': 'bootcamp'}), (self.url(), {}), ('/api/v1/home/', {})]
        small = [capture(*spec) for spec in urls]
        for _ in range(19): self.bootcamp()
        for i in range(10):
            teacher = self.user(f'teacher{i}', 'instructor', verification_status='verified')
            CourseInstructor.objects.create(course=self.course, instructor=teacher, role='guest')
        large = [capture(*spec) for spec in urls]
        self.assertEqual(small, large)
        print(f'PERF list/detail/home 1/20 courses: {small}/{large} queries')

    def test_certificate_reuses_course_criteria(self):
        self.enroll('completed')
        response = self.client.post(self.url('certificate/'))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Certificate.objects.get().course, self.course)

    def test_seed_idempotent_counts_and_progress(self):
        self.student.email = 'student@skillsikka.com'; self.student.save(); self.course.delete()
        out = StringIO(); call_command('seed_bootcamps', stdout=out)
        models = [Course, BootcampProfile, CourseInstructor, Lesson, BootcampResource, BootcampDiscussion, DiscussionLike, Enrollment, LessonProgress]
        first = [model.objects.count() for model in models]
        call_command('seed_bootcamps', stdout=out)
        self.assertEqual(first, [model.objects.count() for model in models])
        self.assertEqual(first, [2, 2, 4, 34, 22, 18, 2, 1, 2])
        for profile in BootcampProfile.objects.all():
            self.assertEqual(set(profile.course.lessons.values_list('day_number', flat=True)), set(range(1, profile.days+1)))
            self.assertTrue(profile.course.lessons.filter(title='Demo', is_preview=True).exists())
            self.assertFalse(profile.course.lessons.filter(duration_seconds=None).exists())
            self.assertEqual(profile.course.instructor, profile.course.instructors.get(role='lead').instructor)
        self.assertEqual(LessonProgress.objects.filter(is_completed=True).count(), 2)
        self.assertEqual(Payment.objects.count(), 0); self.assertIn('shortfall: 6', out.getvalue())

    def test_seed_without_verified_instructor_fails(self):
        from django.core.management.base import CommandError
        User.objects.filter(role__name='instructor').update(verification_status='pending')
        before = Course.objects.count()
        with self.assertRaises(CommandError): call_command('seed_bootcamps', stdout=StringIO())
        self.assertEqual(Course.objects.count(), before)

    def test_profile_required_fields(self):
        for key in ['venue_name', 'days', 'starts_on', 'ends_on']:
            data = self.payload(); del data['bootcamp_profile'][key]
            self.assertEqual(self.post_course(data).status_code, 400)

    def test_atomic_update_rollback(self):
        self.client.force_authenticate(self.admin)
        with patch('core.serializers.CourseInstructor.objects.bulk_create', side_effect=IntegrityError('fixture failure')):
            with self.assertRaises(IntegrityError):
                self.client.patch(self.url(), {'title': 'Rollback', 'bootcamp_profile': {'venue_name': 'Rollback'},
                    'instructors': [{'instructor': self.lead.pk, 'role': 'lead'}]}, format='json')
        self.course.refresh_from_db()
        self.assertEqual(self.course.title, 'ICT & AI Bootcamp')
        self.assertEqual(self.course.bootcamp_profile.venue_name, 'Sundarbazar')
        self.assertEqual(self.course.instructors.count(), 2)

    def test_null_body_stable_error(self):
        self.enroll()
        self.error(self.client.post(self.url('discussions/'), {'body': None}, format='json'), 'BODY_REQUIRED')

    def test_preview_duration_validation(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.patch(f'/api/v1/lessons/{self.lesson.pk}/', {'duration_seconds': -1}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(f'/api/v1/lessons/{self.lesson.pk}/', {'day_number': None}, format='json').status_code, 200)

    def test_discussion_pending_cancelled_cannot_post(self):
        for state in ['pending_payment', 'cancelled']:
            self.enroll(state)
            self.error(self.client.post(self.url('discussions/'), {'body': 'Hello'}, format='json'), 'NOT_ENROLLED', 403)
        self.enroll('completed')
        self.assertEqual(self.client.post(self.url('discussions/'), {'body': 'Hello'}, format='json').status_code, 201)

    def test_student_can_delete_own_reply(self):
        thread = self.discussion(author=self.coach)
        reply = self.discussion(parent=thread)
        self.assertEqual(self.client.delete(self.url(f'discussions/{reply.pk}/')).status_code, 204)
        self.assertTrue(BootcampDiscussion.objects.filter(pk=thread.pk).exists())

    def test_draft_discussions_are_private(self):
        self.course.is_published = False; self.course.save()
        self.error(self.client.get(self.url('discussions/')), 'COURSE_NOT_PUBLISHED', 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.url('discussions/')).status_code, 200)

    def test_legacy_course_form_cannot_create_incomplete_bootcamp(self):
        from core.forms import CourseForm
        form = CourseForm(data={'title': 'Incomplete', 'instructor': self.lead.pk, 'course_type': 'bootcamp'})
        self.assertFalse(form.is_valid()); self.assertIn('course_type', form.errors)

    def test_quiz_ecosystem_bootcamp_authoring_admin_only(self):
        from core.models import Quiz, Question, QuestionOption
        quiz = Quiz.objects.create(course=self.course, title='Check')
        question = Question.objects.create(quiz=quiz, text='Question', marks=1)
        option = QuestionOption.objects.create(question=question, text='Answer', is_correct=True)
        self.client.force_authenticate(self.lead)
        for url, data in [('/api/v1/quizzes/', {'course': self.course.pk, 'title': 'New'}),
                ('/api/v1/questions/', {'quiz': quiz.pk, 'text': 'New', 'marks': 1}),
                ('/api/v1/question-options/', {'question': question.pk, 'text': 'New', 'is_correct': False})]:
            self.error(self.client.post(url, data, format='json'), 'ADMIN_ONLY', 403)
        for url, data in [(f'/api/v1/quizzes/{quiz.pk}/', {'title': 'Bad'}),
                (f'/api/v1/questions/{question.pk}/', {'text': 'Bad'}),
                (f'/api/v1/question-options/{option.pk}/', {'text': 'Bad'})]:
            self.error(self.client.patch(url, data, format='json'), 'ADMIN_ONLY', 403)
            self.error(self.client.delete(url), 'ADMIN_ONLY', 403)

    def test_progress_reviews_and_badge_streak_hooks_reused(self):
        self.enroll()
        response = self.client.post(f'/api/v1/lessons/{self.lesson.pk}/complete/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(LessonProgress.objects.get(student=self.student, lesson=self.lesson).is_completed)
        from core.models import LearningStreak
        self.assertTrue(LearningStreak.objects.filter(student=self.student).exists())
        response = self.client.post(self.url('reviews/'), {'rating': 5, 'review': 'Helpful'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.client.get(self.url()).data['review_count'], 1)

    def test_schema_bootcamp_contracts(self):
        from contextlib import redirect_stderr
        from drf_spectacular.generators import SchemaGenerator
        with redirect_stderr(StringIO()): schema = SchemaGenerator().get_schema(public=True)
        components = schema['components']['schemas']
        self.assertTrue({'BootcampCard', 'BootcampDetail', 'BootcampProfile', 'BootcampDiscussion', 'BootcampResource'} <= set(components))
        self.assertTrue(components['Course']['properties']['lead_instructor_id']['writeOnly'])
        self.assertTrue({'day_number', 'is_completed'} <= set(components['Lesson']['properties']))
        self.assertIn('bootcamps', components['HomeResponse']['properties'])
        for suffix in ['resources/', 'resources/{resource_id}/', 'discussions/', 'discussions/{discussion_id}/', 'discussions/{discussion_id}/like/']:
            self.assertIn('/api/v1/courses/{course_id}/' + suffix, schema['paths'])
        self.assertTrue({'resources_count', 'discussions_count'} <= set(components['BootcampDetail']['properties']))
        self.assertIn('BootcampStatusEnum', components)


from core import test_payments as payment_test_cases


class BootcampPaymentFlowTests(payment_test_cases.PaymentFlowTests):
    """Run the unchanged provider contract suite against a paid bootcamp."""
    def setUp(self):
        super().setUp()
        self.course.course_type = 'bootcamp'
        self.course.save(update_fields=['course_type'])
        BootcampProfile.objects.create(course=self.course, venue_name='Payment fixture', days=1,
            starts_on=date(2026, 9, 21), ends_on=date(2026, 9, 21))
