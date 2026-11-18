from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Course, Enrollment, Lesson, LessonProgress, LessonWatchTime, Payment, Role, User


TODAY = date(2026, 11, 17)


def at(day, hour=12):
    return datetime(day.year, day.month, day.day, hour, tzinfo=dt_timezone.utc)


class AnalyticsSetup(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='owner@example.com', name='Owner',
            role=Role.objects.get(name='instructor'), verification_status='verified')
        self.other_instructor = User.objects.create_user(email='other@example.com', name='Other',
            role=Role.objects.get(name='instructor'), verification_status='verified')
        self.admin = User.objects.create_user(email='admin@example.com', name='Admin', role=Role.objects.get(name='super_admin'))
        self.course = Course.objects.create(title='Interaction design', instructor=self.owner, course_type='skill',
            is_paid=True, price=Decimal('1000.00'), is_published=False)
        Course.objects.filter(pk=self.course.pk).update(created_at=at(date(2026, 11, 1)))
        self.course.refresh_from_db()
        self.l1 = Lesson.objects.create(course=self.course, title='One', section='Basics', order=1, content_type='text')
        self.l2 = Lesson.objects.create(course=self.course, title='Two', section='Basics', order=2, content_type='text')
        self.l3 = Lesson.objects.create(course=self.course, title='Three', section='', order=3, content_type='text')
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.url = f'/api/v1/courses/{self.course.pk}/instructor-analytics/'
        self._students = 0

    def student(self):
        self._students += 1
        return User.objects.create_user(email=f'student{self._students}@example.com', name=f'Student {self._students}',
            role=Role.objects.get(name='student'))

    def enroll(self, on, status='active', source='unknown', student=None):
        enrollment = Enrollment.objects.create(student=student or self.student(), course=self.course, status=status, source=source)
        Enrollment.objects.filter(pk=enrollment.pk).update(enrolled_at=at(on))
        return enrollment

    def pay(self, enrollment, amount, on, status='successful'):
        return Payment.objects.create(student=enrollment.student, course=self.course, enrollment=enrollment,
            amount=Decimal(amount), provider='khalti', transaction_reference=f'ref-{Payment.objects.count()}',
            status=status, verified_at=at(on) if status != 'initiated' else None)

    def get(self, period=None):
        params = {'period': period} if period else {}
        with patch('core.instructor_analytics._today', return_value=TODAY):
            response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data


class InstructorAnalyticsAccessTests(AnalyticsSetup):
    def test_owner_of_a_draft_and_admins_can_read(self):
        self.assertEqual(self.get()['period'], '30d')
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.get('7d')['period'], '7d')

    def test_everyone_else_is_refused(self):
        for user in (self.other_instructor, self.student()):
            self.client.force_authenticate(user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.data['code'], 'NOT_COURSE_OWNER')
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_unknown_course_and_period(self):
        self.assertEqual(self.client.get('/api/v1/courses/999999/instructor-analytics/').status_code, 404)
        response = self.client.get(self.url, {'period': '14d'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'INVALID_PERIOD')


class InstructorAnalyticsWindowTests(AnalyticsSetup):
    def test_fixed_windows_are_inclusive_and_same_length(self):
        body = self.get('7d')
        self.assertEqual((body['period_start'], body['period_end']), ('2026-11-11', '2026-11-17'))
        self.assertEqual((body['previous_period_start'], body['previous_period_end']), ('2026-11-04', '2026-11-10'))
        self.assertEqual([d['date'] for d in body['enrollments_by_day']],
                         [(date(2026, 11, 11) + timedelta(days=i)).isoformat() for i in range(7)])
        body = self.get('30d')
        self.assertEqual((body['period_start'], body['previous_period_start'], body['previous_period_end']),
                         ('2026-10-19', '2026-09-19', '2026-10-18'))
        self.assertEqual(len(body['enrollments_by_day']), 30)

    def test_all_runs_from_course_creation_without_a_previous_window(self):
        self.pay(self.enroll(date(2026, 11, 3)), '1000.00', date(2026, 11, 3))
        body = self.get('all')
        self.assertEqual((body['period_start'], body['period_end']), ('2026-11-01', '2026-11-17'))
        self.assertIsNone(body['previous_period_start'])
        self.assertIsNone(body['previous_period_end'])
        self.assertEqual(len(body['enrollments_by_day']), 17)
        for value in (body['revenue']['delta_percent'], body['students']['delta_percent'],
                      body['watch_time_delta_percent'], body['avg_completion_delta_points']):
            self.assertIsNone(value)


class InstructorAnalyticsStudentAndRevenueTests(AnalyticsSetup):
    def test_new_enrollments_count_from_activation(self):
        self.enroll(date(2026, 11, 15))
        self.enroll(date(2026, 11, 12), status='completed')
        self.enroll(date(2026, 11, 5))                        # previous window
        self.enroll(date(2026, 11, 16), status='pending_payment')
        self.enroll(date(2026, 11, 16), status='cancelled')
        paid = self.enroll(date(2026, 11, 1))                 # joined early, paid on the 16th
        self.pay(paid, '1000.00', date(2026, 11, 16))
        body = self.get('7d')
        self.assertEqual(body['students'], {'enrolled_now': 4, 'new_in_period': 3, 'delta_percent': 200.0})
        counts = {row['date']: row['count'] for row in body['enrollments_by_day']}
        self.assertEqual((counts['2026-11-12'], counts['2026-11-15'], counts['2026-11-16'], counts['2026-11-11']), (1, 1, 1, 0))
        self.assertIsNone(self.get('90d')['students']['delta_percent'])

    def test_revenue_sums_successful_payments_in_the_window(self):
        self.pay(self.enroll(date(2026, 11, 16)), '1000.00', date(2026, 11, 16))
        self.pay(self.enroll(date(2026, 11, 14)), '500.50', date(2026, 11, 14))
        self.pay(self.enroll(date(2026, 11, 15), status='pending_payment'), '999.00', date(2026, 11, 15), status='failed')
        self.pay(self.enroll(date(2026, 11, 15), status='pending_payment'), '999.00', date(2026, 11, 15), status='cancelled')
        self.pay(self.enroll(date(2026, 11, 6)), '800.00', date(2026, 11, 6))
        self.assertEqual(self.get('7d')['revenue'], {'amount': '1500.50', 'currency': 'NPR', 'delta_percent': 87.6})

    def test_no_revenue_is_a_real_zero_with_no_delta(self):
        self.assertEqual(self.get('7d')['revenue'], {'amount': '0.00', 'currency': 'NPR', 'delta_percent': None})


class InstructorAnalyticsCompletionTests(AnalyticsSetup):
    def complete(self, enrollment, lesson, on):
        LessonProgress.objects.create(student=enrollment.student, lesson=lesson, enrollment=enrollment,
            is_completed=True, completed_at=at(on))

    def test_average_completion_retention_and_delta_points(self):
        a, b, _c = (self.enroll(date(2026, 11, 1)) for _ in range(3))
        self.complete(a, self.l1, date(2026, 11, 8))
        self.complete(a, self.l2, date(2026, 11, 16))
        self.complete(a, self.l3, date(2026, 11, 16))
        self.complete(b, self.l1, date(2026, 11, 8))
        gone = self.enroll(date(2026, 11, 1), status='cancelled')
        for lesson in (self.l1, self.l2, self.l3):
            self.complete(gone, lesson, date(2026, 11, 2))
        body = self.get('7d')
        # Now: (3/3 + 1/3 + 0) / 3. On the 10th: (1/3 + 1/3 + 0) / 3.
        self.assertEqual(body['avg_completion_percent'], 44.4)
        self.assertEqual(body['avg_completion_delta_points'], 22.2)
        self.assertEqual(body['retention'], [
            {'section': 'Basics', 'lesson_count': 2, 'completion_percent': 33.3},
            {'section': 'Lessons', 'lesson_count': 1, 'completion_percent': 33.3},
        ])

    def test_nothing_to_measure_is_null_and_zero_is_zero(self):
        body = self.get('7d')
        self.assertIsNone(body['avg_completion_percent'])
        self.assertEqual([row['completion_percent'] for row in body['retention']], [None, None])
        self.enroll(date(2026, 11, 1))
        body = self.get('7d')
        self.assertEqual(body['avg_completion_percent'], 0.0)
        self.assertEqual([row['completion_percent'] for row in body['retention']], [0.0, 0.0])
        Lesson.objects.filter(course=self.course).delete()
        body = self.get('7d')
        self.assertIsNone(body['avg_completion_percent'])
        self.assertEqual(body['retention'], [])

    def test_query_count_does_not_grow_with_students(self):
        def queries():
            with CaptureQueriesContext(connection) as captured:
                self.get('30d')
            return len(captured)
        for _ in range(2):
            self.complete(self.enroll(date(2026, 11, 10)), self.l1, date(2026, 11, 12))
        baseline = queries()
        for _ in range(10):
            enrollment = self.enroll(date(2026, 11, 10))
            self.pay(enrollment, '1000.00', date(2026, 11, 10))
            self.complete(enrollment, self.l1, date(2026, 11, 12))
        self.assertEqual(queries(), baseline)


class InstructorAnalyticsWatchTimeTests(AnalyticsSetup):
    def setUp(self):
        super().setUp()
        self.enrollment = self.enroll(date(2026, 11, 1))
        self.learner = self.enrollment.student
        self.progress_url = f'/api/v1/lessons/{self.l1.pk}/progress/'

    def report(self, payload, user=None):
        self.client.force_authenticate(user or self.learner)
        return self.client.post(self.progress_url, payload, format='json')

    def test_reports_add_up_and_are_capped_by_wall_clock(self):
        response = self.report({'watched_seconds': 30, 'position_seconds': 124})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data['credited_seconds'], response.data['total_watched_seconds'],
                          response.data['position_seconds']), (30, 30, 124))
        # A replay straight away can only claim the few seconds that passed.
        response = self.report({'watched_seconds': 30, 'position_seconds': 130})
        self.assertLessEqual(response.data['credited_seconds'], 6)
        self.assertEqual(response.data['position_seconds'], 130)
        LessonWatchTime.objects.update(updated_at=timezone.now() - timedelta(seconds=60))
        response = self.report({'watched_seconds': 30})
        self.assertEqual(response.data['credited_seconds'], 30)
        self.assertEqual(response.data['position_seconds'], 130)
        row = LessonWatchTime.objects.get()
        self.assertEqual(row.watched_seconds, response.data['total_watched_seconds'])
        self.assertEqual(row.date, timezone.localdate())

    def test_bad_reports_and_who_may_report(self):
        for payload in ({}, {'watched_seconds': 0}, {'watched_seconds': 121}, {'watched_seconds': 10, 'position_seconds': -1}):
            self.assertEqual(self.report(payload).status_code, 400, payload)
        outsider = self.student()
        response = self.report({'watched_seconds': 10}, outsider)
        self.assertEqual((response.status_code, response.data['code']), (403, 'NOT_ENROLLED'))
        self.assertEqual(self.report({'watched_seconds': 10}, self.owner).status_code, 403)
        self.client.force_authenticate(self.learner)
        self.assertEqual(self.client.post('/api/v1/lessons/999999/progress/', {'watched_seconds': 10}, format='json').status_code, 404)
        self.assertFalse(LessonWatchTime.objects.exists())

    def test_analytics_sum_the_window_and_stay_null_until_recorded(self):
        body = self.get('7d')
        self.assertIsNone(body['watch_time_seconds'])
        self.assertIsNone(body['watch_time_delta_percent'])
        LessonWatchTime.objects.create(student=self.learner, lesson=self.l1, date=date(2026, 11, 16), watched_seconds=300)
        LessonWatchTime.objects.create(student=self.learner, lesson=self.l2, date=date(2026, 11, 11), watched_seconds=150)
        LessonWatchTime.objects.create(student=self.learner, lesson=self.l1, date=date(2026, 11, 8), watched_seconds=200)
        body = self.get('7d')
        self.assertEqual((body['watch_time_seconds'], body['watch_time_delta_percent']), (450, 125.0))


class InstructorAnalyticsSourceTests(AnalyticsSetup):
    def setUp(self):
        super().setUp()
        self.course.is_paid = False
        self.course.price = None
        self.course.is_published = True
        self.course.save()
        self.enroll_url = f'/api/v1/courses/{self.course.pk}/enroll/'

    def enroll_via_api(self, payload):
        self.client.force_authenticate(self.student())
        response = self.client.post(self.enroll_url, payload, format='json')
        self.client.force_authenticate(self.owner)
        return response

    def test_source_is_optional_and_validated(self):
        self.assertEqual(self.enroll_via_api({}).status_code, 201)
        self.assertEqual(self.enroll_via_api({'source': 'social'}).status_code, 201)
        response = self.enroll_via_api({'source': 'billboard'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('source', response.data)
        self.assertEqual(sorted(Enrollment.objects.values_list('source', flat=True)), ['social', 'unknown'])

    def test_sources_empty_until_a_real_source_then_shares_of_new_enrollments(self):
        self.enroll_via_api({})
        self.assertEqual(self.client.get(self.url, {'period': '7d'}).data['sources'], [])
        for payload in ({'source': 'social'}, {'source': 'direct'}, {'source': 'social'}):
            self.assertEqual(self.enroll_via_api(payload).status_code, 201)
        sources = self.client.get(self.url, {'period': '7d'}).data['sources']
        self.assertEqual(sources, [
            {'key': 'direct', 'share_percent': 25.0, 'conversion_percent': None},
            {'key': 'organic', 'share_percent': 0.0, 'conversion_percent': None},
            {'key': 'social', 'share_percent': 50.0, 'conversion_percent': None},
            {'key': 'unknown', 'share_percent': 25.0, 'conversion_percent': None},
        ])


class InstructorCourseLibraryContractTests(AnalyticsSetup):
    """The My Courses list the app already relies on must keep its shape."""

    def test_owner_sees_drafts_with_every_field_the_app_reads(self):
        response = self.client.get('/api/v1/courses/', {'instructor': self.owner.pk, 'page_size': 50})
        self.assertEqual(response.status_code, 200)
        self.assertIn('next', response.data)
        row = next(r for r in response.data['results'] if r['id'] == self.course.pk)
        for key in ('id', 'title', 'is_published', 'is_paid', 'price', 'thumbnail_url', 'lessons_count',
                    'total_duration_seconds', 'premium_category_name', 'skill_category_name', 'subject_name',
                    'updated_at', 'course_type'):
            self.assertIn(key, row)
        self.assertFalse(row['is_published'])
        self.assertEqual(row['lessons_count'], 3)
        self.client.force_authenticate(self.student())
        ids = [r['id'] for r in self.client.get('/api/v1/courses/', {'instructor': self.owner.pk}).data['results']]
        self.assertNotIn(self.course.pk, ids)
