import io
import shutil
import tempfile
import json
import re
import urllib.error
import urllib.request
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from django.test import TestCase, LiveServerTestCase, override_settings
from django.db import connection, IntegrityError, transaction
from django.core.cache import cache
from django.core import mail
from django.contrib.auth.hashers import check_password
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient

from .models import District, Grade, InstructorProfile, Municipality, Permission, Province, Role, School, StudentProfile, User, VerificationDocument
from .signup_otp import OTP_EXPIRY_SECONDS
from .models import Short, ShortBookmark, ShortComment, ShortLike, ShortView
from .models import PasswordResetOTP
from .serializers import ShortSerializer
from .models import Course, CourseReview, Enrollment, Lesson, LessonProgress, with_instructor_review_stats
from .serializers import CourseSerializer


class NotificationIntegrationTests(TestCase):
    def setUp(self):
        from .models import Notification, Reward, PointTransaction
        self.notifications = Notification.objects
        self.client = APIClient()
        self.student = self.user('NotifyStudent', 'student')
        self.other = self.user('NotifyOther', 'student')
        self.teacher = self.user('NotifyTeacher', 'instructor')
        self.admin = self.user('NotifyAdmin', 'super_admin')
        self.course = Course.objects.create(title='Notification course', course_type='skill',
            instructor=self.teacher, is_published=True)
        self.lesson = Lesson.objects.create(course=self.course, title='Lesson', content_type='text', order=1)
        self.reward = Reward.objects.create(name='Book', points_required=40, stock=3)
        PointTransaction.objects.create(student=self.student, points=100, event_type='manual_adjustment')
        self.client.force_authenticate(self.student)

    def user(self, name, role):
        return User.objects.create_user(email=f'{name.lower()}@example.com', name=name,
            role=Role.objects.get(name=role))

    def notice(self, recipient=None, **fields):
        return self.notifications.create(recipient=recipient or self.student, notification_type='system',
            title='Notice', message='Safe message', **fields)

    def enroll_completed(self, course=None):
        course = course or self.course
        enrollment = Enrollment.objects.create(student=self.student, course=course)
        lesson = self.lesson if course == self.course else Lesson.objects.create(course=course, title='Lesson', content_type='text')
        LessonProgress.objects.create(student=self.student, lesson=lesson, enrollment=enrollment,
            is_completed=True, completed_at=timezone.now())
        return enrollment

    def redeem(self):
        self.client.force_authenticate(self.student)
        response = self.client.post(reverse('api-redeem-reward'), {'reward_id': self.reward.pk}, format='json')
        self.assertEqual(response.status_code, 201)
        return response.data['redemption']['id']

    def transition(self, redemption_id, state, **fields):
        self.client.force_authenticate(self.admin)
        return self.client.patch(reverse('api-admin-redemption-detail', args=[redemption_id]),
            {'status': state, **fields}, format='json')

    def event(self, **fields):
        from .models import Event
        now = timezone.now()
        return Event.objects.create(title='Bootcamp', host=self.teacher, is_published=True,
            start_at=now + timedelta(days=1), end_at=now + timedelta(days=2), **fields)

    def test_list_ownership_fields_and_constant_queries(self):
        own = self.notice()
        self.notice(self.other)
        with self.assertNumQueries(1):
            response = self.client.get(reverse('notification-list'), {'user_id': self.other.pk})
        self.assertEqual([n['id'] for n in response.data], [own.pk])
        self.assertEqual(set(response.data[0]), {'id', 'notification_type', 'title', 'message',
            'related_type', 'related_id', 'is_read', 'read_at', 'created_at'})
        for _ in range(10):
            self.notice()
        with self.assertNumQueries(1):
            self.assertEqual(len(self.client.get(reverse('notification-list')).data), 11)

    def test_read_filter_count_mark_one_and_idempotency(self):
        unread = self.notice()
        read = self.notice(is_read=True, read_at=timezone.now())
        self.notice(self.other)
        self.assertEqual(self.client.get(reverse('notification-unread-count')).data, {'unread_count': 1})
        self.assertEqual([n['id'] for n in self.client.get(reverse('notification-list'), {'is_read': 'false'}).data], [unread.pk])
        self.assertEqual([n['id'] for n in self.client.get(reverse('notification-list'), {'is_read': 'true'}).data], [read.pk])
        url = reverse('notification-mark-read', args=[unread.pk])
        first = self.client.post(url).data
        self.assertTrue(first['is_read'])
        self.assertIsNotNone(first['read_at'])
        self.assertEqual(self.client.post(url).data, first)
        self.assertEqual(self.client.get(reverse('notification-unread-count')).data, {'unread_count': 0})

    def test_mark_all_read_scoped_and_repeated_safe(self):
        own = [self.notice(), self.notice()]
        other = self.notice(self.other)
        response = self.client.post(reverse('notification-mark-all-read'), {'user_id': self.other.pk})
        self.assertEqual(response.data, {'detail': '2 notification(s) marked as read.'})
        timestamps = []
        for notice in own:
            notice.refresh_from_db()
            self.assertTrue(notice.is_read)
            timestamps.append(notice.read_at)
        self.assertEqual(self.client.post(reverse('notification-mark-all-read')).data, {'detail': '0 notification(s) marked as read.'})
        self.assertEqual(list(self.notifications.filter(pk__in=[n.pk for n in own]).order_by('pk').values_list('read_at', flat=True)), timestamps)
        other.refresh_from_db()
        self.assertFalse(other.is_read)

    def test_cannot_read_or_update_another_users_notification(self):
        other = self.notice(self.other)
        self.assertEqual(self.client.post(reverse('notification-mark-read', args=[other.pk])).status_code, 404)
        self.assertEqual(self.client.patch(reverse('notification-mark-read', args=[other.pk]), {'is_read': True}).status_code, 405)
        other.refresh_from_db()
        self.assertFalse(other.is_read)

    def test_anonymous_notification_access_denied(self):
        self.client.force_authenticate(None)
        for name in ['notification-list', 'notification-unread-count']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 401)
        self.assertEqual(self.client.post(reverse('notification-mark-all-read')).status_code, 401)
        self.assertEqual(self.client.post(reverse('notification-mark-read', args=[1])).status_code, 401)

    def test_reward_submission_approval_fulfillment_notify_once_each(self):
        redemption_id = self.redeem()
        for state in ['approved', 'fulfilled']:
            for _ in range(2):
                self.assertEqual(self.transition(redemption_id, state, note='PRIVATE ADMIN NOTE').status_code, 200)
        notices = self.notifications.filter(recipient=self.student, related_type='redemption', related_id=redemption_id).order_by('pk')
        self.assertEqual(list(notices.values_list('title', flat=True)), ['Reward redemption submitted', 'Reward redemption approved', 'Reward redemption fulfilled'])
        self.assertTrue(all(n.notification_type == 'system' for n in notices))
        self.assertNotIn('PRIVATE ADMIN NOTE', ' '.join(n.message for n in notices))
        self.assertEqual(self.notifications.exclude(recipient=self.student).count(), 0)

    def test_reward_rejection_and_cancellation_notify_once(self):
        for state in ['rejected', 'cancelled']:
            redemption_id = self.redeem()
            for _ in range(3):
                self.assertEqual(self.transition(redemption_id, state).status_code, 200)
            notices = self.notifications.filter(related_type='redemption', related_id=redemption_id)
            self.assertEqual(notices.count(), 2)
            self.assertIn('40 points have been refunded.', notices.get(title=f'Reward redemption {state}').message)
            self.assertEqual(self.transition(redemption_id, 'approved').status_code, 400)
            self.assertEqual(notices.count(), 2)

    def test_reward_notification_rollback_and_failure_atomicity(self):
        from .models import Redemption, PointTransaction
        redemption_id = self.redeem()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.assertEqual(self.transition(redemption_id, 'rejected').status_code, 200)
                raise RuntimeError('Rollback outer transaction')
        self.assertEqual(Redemption.objects.get(pk=redemption_id).status, 'pending')
        self.assertEqual(self.notifications.filter(related_id=redemption_id, related_type='redemption').count(), 1)
        with patch('core.api_views._notify', side_effect=RuntimeError('Notification write failed')):
            with self.assertRaises(RuntimeError):
                self.transition(redemption_id, 'rejected')
        self.assertEqual(Redemption.objects.get(pk=redemption_id).status, 'pending')
        self.assertEqual(PointTransaction.objects.filter(student=self.student).count(), 2)
        self.reward.refresh_from_db()
        self.assertEqual(self.reward.stock, 2)

    def test_reward_submission_notification_failure_rolls_back(self):
        from .models import Redemption, PointTransaction
        with patch('core.api_views._notify', side_effect=RuntimeError('Notification write failed')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('api-redeem-reward'), {'reward_id': self.reward.pk}, format='json')
        self.assertFalse(Redemption.objects.exists())
        self.assertEqual(PointTransaction.objects.filter(student=self.student).count(), 1)
        self.reward.refresh_from_db()
        self.assertEqual(self.reward.stock, 3)
        self.assertFalse(self.notifications.exists())

    def test_free_enrollment_confirmation_only_on_creation(self):
        url = reverse('api-enroll-course', args=[self.course.pk])
        self.assertEqual(self.client.post(url).status_code, 201)
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assertEqual(self.notifications.filter(title='Course access confirmed', related_id=self.course.pk).count(), 1)

    def test_course_progress_completion_not_repeated_by_my_learning(self):
        self.enroll_completed()
        url = reverse('api-course-progress', args=[self.course.pk])
        for _ in range(2):
            self.assertTrue(self.client.get(url).data['is_completed'])
            self.assertEqual(self.client.get(reverse('api-my-learning')).status_code, 200)
        notice = self.notifications.get(title='Course completed')
        self.assertEqual((notice.recipient_id, notice.related_type, notice.related_id), (self.student.pk, 'course', self.course.pk))

    def test_my_learning_completion_batch_has_no_query_growth(self):
        self.enroll_completed()
        with CaptureQueriesContext(connection) as first:
            self.assertEqual(self.client.get(reverse('api-my-learning')).status_code, 200)
        for i in range(5):
            course = Course.objects.create(title=f'Other course {i}', instructor=self.teacher, course_type='skill')
            self.enroll_completed(course)
        with CaptureQueriesContext(connection) as many:
            self.assertEqual(self.client.get(reverse('api-my-learning')).status_code, 200)
        self.assertEqual(len(first), len(many))
        self.assertEqual(self.notifications.filter(title='Course completed').count(), 6)

    def test_stale_completion_requests_are_guarded_by_locked_state(self):
        from .api_views import _apply_course_completion, _persist_course_completions
        enrollment = self.enroll_completed()
        stale = Enrollment.objects.select_related('course').get(pk=enrollment.pk)
        current = Enrollment.objects.select_related('course').get(pk=enrollment.pk)
        _apply_course_completion(current, True)
        _apply_course_completion(stale, True)
        _persist_course_completions([current])
        _persist_course_completions([stale])
        self.assertEqual(self.notifications.filter(title='Course completed').count(), 1)

    def test_completion_notification_failure_rolls_back_transition(self):
        from .models import Notification
        enrollment = self.enroll_completed()
        with patch.object(Notification.objects, 'bulk_create', side_effect=RuntimeError('Notification write failed')):
            with self.assertRaises(RuntimeError):
                self.client.get(reverse('api-course-progress', args=[self.course.pk]))
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, 'active')
        self.assertFalse(self.notifications.exists())

    def test_incomplete_zero_lesson_and_historical_completion_do_not_notify(self):
        Enrollment.objects.create(student=self.student, course=self.course)
        empty = Course.objects.create(title='Empty', instructor=self.teacher, course_type='skill')
        Enrollment.objects.create(student=self.student, course=empty)
        historical = Course.objects.create(title='Historical', instructor=self.teacher, course_type='skill')
        Enrollment.objects.create(student=self.student, course=historical, status='completed')
        self.client.get(reverse('api-my-learning'))
        self.assertFalse(self.notifications.filter(title='Course completed').exists())

    def test_course_certificate_notifies_once_and_failure_rolls_back(self):
        from .models import Certificate, CertificateCriteria
        enrollment = self.enroll_completed()
        enrollment.status = 'completed'
        enrollment.save()
        criteria = CertificateCriteria.get_solo()
        criteria.skill_course_requires_quiz_pass = False
        criteria.save()
        url = reverse('api-check-course-certificate', args=[self.course.pk])
        with patch('core.api_views._notify', side_effect=RuntimeError('Notification write failed')):
            with self.assertRaises(RuntimeError):
                self.client.post(url)
        self.assertFalse(Certificate.objects.exists())
        first = self.client.post(url)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.notifications.filter(notification_type='certificate', related_id=first.data['id']).count(), 1)

    def test_grade_certificate_notifies_once(self):
        from .models import Certificate
        grade = Grade.objects.create(name='Notification grade')
        StudentProfile.objects.create(user=self.student, grade=grade)
        course = Course.objects.create(title='Academic', course_type='academic', grade=grade, instructor=self.teacher, is_published=True)
        self.enroll_completed(course)
        url = reverse('api-check-grade-certificate')
        first = self.client.post(url)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(Certificate.objects.filter(student=self.student, grade=grade).count(), 1)
        self.assertEqual(self.notifications.filter(notification_type='certificate').count(), 1)

    def test_event_registration_waitlist_cancellation_and_promotion(self):
        event = self.event(capacity=1)
        url = reverse('api-event-register', args=[event.pk])
        self.assertEqual(self.client.post(url).status_code, 201)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(url).status_code, 201)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(list(self.notifications.filter(recipient=self.student).order_by('pk').values_list('title', flat=True)),
            ['Event registration confirmed', 'Event registration cancelled'])
        self.assertEqual(list(self.notifications.filter(recipient=self.other).order_by('pk').values_list('title', flat=True)),
            ['Event waitlisted', 'Event registration confirmed'])

    def test_event_notification_failure_rolls_back_registration(self):
        from .models import EventRegistration
        event = self.event()
        with patch('core.event_views._notify', side_effect=RuntimeError('Notification write failed')):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse('api-event-register', args=[event.pk]))
        self.assertFalse(EventRegistration.objects.exists())
        self.assertFalse(self.notifications.exists())

    def test_existing_instructor_verification_trigger_preserved_and_safe(self):
        self.client.force_authenticate(self.admin)
        url = reverse('api-admin-instructor-verification', args=[self.teacher.pk])
        for state in ['verified', 'rejected']:
            response = self.client.patch(url, {'verification_status': state, 'notes': 'PRIVATE REVIEW NOTES'}, format='json')
            self.assertEqual(response.status_code, 200)
        notices = self.notifications.filter(recipient=self.teacher)
        self.assertEqual(notices.count(), 2)
        for notice in notices:
            self.assertNotIn('PRIVATE REVIEW NOTES', notice.message)
            self.assertNotIn(self.teacher.email, notice.message)
            self.assertNotIn(self.admin.email, notice.message)


class RewardTestSetup(TestCase):
    def setUp(self):
        from .models import Reward, PointTransaction
        self.client = APIClient()
        self.admin = self.user('RewardAdmin', 'super_admin')
        self.student = self.user('RewardStudent', 'student')
        self.other = self.user('RewardOther', 'student')
        self.reward = Reward.objects.create(name='Book', points_required=40, stock=3)
        PointTransaction.objects.create(student=self.student, points=100, event_type='manual_adjustment')
        self.list_url = reverse('api-admin-rewards')
        self.detail_url = reverse('api-admin-reward-detail', args=[self.reward.pk])
        self.redemptions_url = reverse('api-admin-redemptions')
        self.client.force_authenticate(self.admin)

    def user(self, name, role, **kwargs):
        return User.objects.create_user(email=f'{name.lower()}@example.com', name=name,
            role=Role.objects.get_or_create(name=role)[0], **kwargs)

    def redeem(self, reward=None):
        from .models import Redemption
        self.client.force_authenticate(self.student)
        response = self.client.post(reverse('api-redeem-reward'), {'reward_id': (reward or self.reward).pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_authenticate(self.admin)
        return Redemption.objects.get(pk=response.data['redemption']['id'])

    def transition(self, redemption, status, **fields):
        return self.client.patch(reverse('api-admin-redemption-detail', args=[redemption.pk]),
            {'status': status, **fields}, format='json')

    def balance(self):
        from .models import PointTransaction
        from django.db.models import Sum
        return PointTransaction.objects.filter(student=self.student).aggregate(total=Sum('points'))['total']

class RewardAdminTests(RewardTestSetup):
    def test_admin_list_detail_create_and_update(self):
        from .models import AuditLog
        self.assertEqual(self.client.get(self.list_url).data[0]['id'], self.reward.pk)
        self.assertEqual(self.client.get(self.detail_url).status_code, 200)
        created = self.client.post(self.list_url, {'name': 'Pen', 'points_required': 10, 'stock': None}, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.data['available'])
        updated = self.client.patch(self.detail_url, {'name': 'New book', 'description': 'Gift',
            'points_required': 50, 'stock': 0, 'is_active': False}, format='json')
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.data['available'])
        self.assertEqual(list(AuditLog.objects.filter(target_type='reward').order_by('pk').values_list('action', flat=True)), ['create', 'update'])

    def test_invalid_points_and_stock(self):
        for value in [0, -1, 'bad', None, 1.5]:
            with self.subTest(points=value):
                self.assertEqual(self.client.post(self.list_url, {'name': 'Bad', 'points_required': value}, format='json').status_code, 400)
                self.assertEqual(self.client.patch(self.detail_url, {'points_required': value}, format='json').status_code, 400)
        for value in [-1, 'bad', 1.5]:
            self.assertEqual(self.client.patch(self.detail_url, {'stock': value}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(self.detail_url, {'stock': None}, format='json').status_code, 200)

    def test_read_only_and_ownership_fields_rejected(self):
        for field in ['student', 'id', 'created_at', 'available', 'status']:
            self.assertEqual(self.client.patch(self.detail_url, {field: 1}, format='json').status_code, 400)
        redemption = self.redeem()
        for field in ['student_id', 'reward_id', 'points_spent']:
            self.assertEqual(self.transition(redemption, 'approved', **{field: 1}).status_code, 400)

    def test_delete_deactivates_preserves_history_and_is_idempotent(self):
        from .models import Reward, Redemption, AuditLog
        redemption = self.redeem()
        for _ in range(2):
            self.assertEqual(self.client.delete(self.detail_url).status_code, 204)
        self.assertTrue(Reward.objects.filter(pk=self.reward.pk, is_active=False).exists())
        self.assertTrue(Redemption.objects.filter(pk=redemption.pk).exists())
        self.assertEqual(AuditLog.objects.filter(action='deactivate', target_type='reward').count(), 1)
        self.assertEqual(self.transition(redemption, 'rejected').status_code, 200)
        self.assertEqual(self.balance(), 100)

    def test_non_admin_roles_denied_on_every_operation(self):
        redemption = self.redeem()
        url = reverse('api-admin-redemption-detail', args=[redemption.pk])
        for role in ['student', 'instructor', 'teacher', 'municipality', 'ministry']:
            self.client.force_authenticate(self.user(f'Denied{role}', role))
            for method, endpoint, data in [('get', self.list_url, None), ('post', self.list_url, {}),
                ('get', self.detail_url, None), ('patch', self.detail_url, {}), ('delete', self.detail_url, None),
                ('get', self.redemptions_url, None), ('get', url, None), ('patch', url, {'status': 'approved'})]:
                with self.subTest(role=role, method=method, endpoint=endpoint):
                    self.assertEqual(getattr(self.client, method)(endpoint, data, format='json').status_code, 403)

    def test_anonymous_denied_and_superuser_allowed(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.list_url).status_code, 401)
        self.client.force_authenticate(self.user('RootReward', 'student', is_superuser=True))
        self.assertEqual(self.client.get(self.list_url).status_code, 200)

    def test_redemption_list_detail_status_filter_privacy(self):
        redemption = self.redeem()
        self.assertEqual(self.transition(redemption, 'approved', note='Ready').status_code, 200)
        listed = self.client.get(self.redemptions_url, {'status': 'approved'}).data
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]['student'], {'id': self.student.pk, 'name': self.student.name})
        self.assertEqual(set(listed[0]), {'id', 'student', 'reward', 'points_spent', 'status', 'note', 'created_at', 'updated_at'})
        self.assertEqual(self.client.get(reverse('api-admin-redemption-detail', args=[redemption.pk])).data, listed[0])
        self.assertEqual(self.client.get(self.redemptions_url, {'status': 'pending'}).data, [])
        self.assertEqual(self.client.get(self.redemptions_url, {'status': 'bad'}).status_code, 400)

    def test_approval_fulfillment_preserves_points_and_stock(self):
        from .models import PointTransaction
        redemption = self.redeem()
        for state in ['approved', 'fulfilled']:
            self.assertEqual(self.transition(redemption, state).status_code, 200)
        self.assertEqual(self.balance(), 60)
        self.assertEqual(PointTransaction.objects.filter(student=self.student).count(), 2)
        self.reward.refresh_from_db()
        self.assertEqual(self.reward.stock, 2)

    def test_invalid_jumps_and_fulfilled_backward_transitions(self):
        redemption = self.redeem()
        self.assertEqual(self.transition(redemption, 'fulfilled').status_code, 400)
        self.assertEqual(self.transition(redemption, 'invalid').status_code, 400)
        self.transition(redemption, 'approved')
        self.assertEqual(self.transition(redemption, 'pending').status_code, 400)
        self.transition(redemption, 'fulfilled')
        for state in ['pending', 'approved', 'rejected', 'cancelled']:
            self.assertEqual(self.transition(redemption, state).status_code, 400)
        self.assertEqual(self.balance(), 60)

    def test_rejection_restores_once_and_preserves_original_deduction(self):
        from .models import PointTransaction, AuditLog
        redemption = self.redeem()
        original_id = redemption.point_transaction_id
        for _ in range(3):
            self.assertEqual(self.transition(redemption, 'rejected', note='Unavailable').status_code, 200)
        redemption.refresh_from_db()
        self.reward.refresh_from_db()
        self.assertEqual((redemption.status, redemption.note, self.reward.stock, self.balance()), ('rejected', 'Unavailable', 3, 100))
        self.assertEqual(redemption.point_transaction_id, original_id)
        self.assertEqual(PointTransaction.objects.get(pk=original_id).points, -40)
        refund = PointTransaction.objects.exclude(pk=original_id).get(student=self.student, points=40)
        self.assertEqual(refund.event_type, 'manual_adjustment')
        self.assertIn(f'#{redemption.pk}', refund.description)
        log = AuditLog.objects.get(target_type='redemption', target_id=redemption.pk)
        self.assertEqual(log.metadata['refund_transaction_id'], refund.pk)
        self.assertNotIn('Unavailable', str(log.metadata))
        for state in ['approved', 'pending', 'cancelled']:
            self.assertEqual(self.transition(redemption, state).status_code, 400)

    def test_approved_rejection_uses_original_price(self):
        redemption = self.redeem()
        self.transition(redemption, 'approved')
        self.client.patch(self.detail_url, {'points_required': 99}, format='json')
        self.assertEqual(self.transition(redemption, 'rejected').status_code, 200)
        self.assertEqual(self.balance(), 100)

    def test_cancellation_pending_and_approved_refunds_once(self):
        for approved in [False, True]:
            redemption = self.redeem()
            if approved:
                self.transition(redemption, 'approved')
            for _ in range(2):
                self.assertEqual(self.transition(redemption, 'cancelled').status_code, 200)
            self.assertEqual(self.transition(redemption, 'rejected').status_code, 400)
            self.assertEqual(self.balance(), 100)
        self.reward.refresh_from_db()
        self.assertEqual(self.reward.stock, 3)

    def test_unlimited_stock_remains_null_on_refund(self):
        self.reward.stock = None
        self.reward.save()
        redemption = self.redeem()
        self.assertEqual(self.transition(redemption, 'rejected').status_code, 200)
        self.reward.refresh_from_db()
        self.assertIsNone(self.reward.stock)
        self.assertEqual(self.balance(), 100)

    def test_stock_mode_changes_blocked_until_reservations_closed(self):
        redemption = self.redeem()
        self.assertEqual(self.client.patch(self.detail_url, {'stock': None}, format='json').status_code, 400)
        self.transition(redemption, 'approved')
        self.assertEqual(self.client.patch(self.detail_url, {'stock': None}, format='json').status_code, 400)
        self.transition(redemption, 'rejected')
        self.assertEqual(self.client.patch(self.detail_url, {'stock': None}, format='json').status_code, 200)
        unlimited = self.redeem()
        self.assertEqual(self.client.patch(self.detail_url, {'stock': 5}, format='json').status_code, 400)
        self.transition(unlimited, 'cancelled')
        self.assertEqual(self.client.patch(self.detail_url, {'stock': 5}, format='json').status_code, 200)

    def test_atomic_failure_rolls_back_refund_stock_status_and_audit(self):
        from .models import AuditLog, PointTransaction
        redemption = self.redeem()
        with patch('core.api_views._create_audit_log', side_effect=RuntimeError('Audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.transition(redemption, 'rejected')
        redemption.refresh_from_db()
        self.reward.refresh_from_db()
        self.assertEqual((redemption.status, self.reward.stock, self.balance()), ('pending', 2, 60))
        self.assertEqual(PointTransaction.objects.filter(student=self.student).count(), 2)
        self.assertFalse(AuditLog.objects.filter(target_type='redemption').exists())
        self.assertEqual(self.transition(redemption, 'rejected').status_code, 200)

    def test_transition_locks_redemption_reward_student_and_retry_noop(self):
        from .models import Reward, Redemption, AuditLog
        managers = [Redemption.objects, Reward.objects, User.objects]
        with patch.object(managers[0], 'select_for_update', wraps=managers[0].select_for_update) as redemption_lock, \
             patch.object(managers[1], 'select_for_update', wraps=managers[1].select_for_update) as reward_lock, \
             patch.object(managers[2], 'select_for_update', wraps=managers[2].select_for_update) as student_lock:
            redemption = self.redeem()
            redemption_lock.reset_mock(); reward_lock.reset_mock(); student_lock.reset_mock()
            self.assertEqual(self.transition(redemption, 'rejected').status_code, 200)
            for lock in [redemption_lock, reward_lock, student_lock]:
                lock.assert_called_once_with()
        before = self.client.get(reverse('api-admin-redemption-detail', args=[redemption.pk])).data
        self.assertEqual(self.transition(redemption, 'rejected', note='Retry changes nothing').data, before)
        self.assertEqual(AuditLog.objects.filter(target_type='redemption').count(), 1)

    def test_list_does_not_query_each_redemption(self):
        from .models import PointTransaction
        PointTransaction.objects.create(student=self.student, points=1000, event_type='manual_adjustment')
        self.reward.stock = None
        self.reward.save()
        for _ in range(5):
            self.redeem()
        with self.assertNumQueries(1):
            self.assertEqual(len(self.client.get(self.redemptions_url).data), 5)

    def test_missing_resources(self):
        self.assertEqual(self.client.get(reverse('api-admin-reward-detail', args=[99999])).status_code, 404)
        self.assertEqual(self.client.patch(reverse('api-admin-redemption-detail', args=[99999]), {'status': 'approved'}, format='json').status_code, 404)


class StudentRewardCompatibilityTests(RewardTestSetup):
    def test_student_listing_redeem_history_and_points(self):
        from .models import Reward
        created = self.client.post(self.list_url, {'name': 'Pen', 'points_required': 10}, format='json')
        self.assertEqual(created.status_code, 201)
        Reward.objects.create(name='Hidden', points_required=1, is_active=False)
        self.client.force_authenticate(self.student)
        listed = self.client.get(reverse('api-rewards')).data
        self.assertEqual({r['id'] for r in listed}, {self.reward.pk, created.data['id']})
        response = self.client.post(reverse('api-redeem-reward'), {'reward_id': self.reward.pk}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['remaining_points'], 60)
        self.assertEqual(response.data['redemption']['status'], 'pending')
        history = self.client.get(reverse('api-my-redemptions')).data
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0], response.data['redemption'])
        self.assertEqual(self.client.get(reverse('student-points')).data['total_points'], 60)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(reverse('api-my-redemptions')).data, [])

    def test_student_insufficient_points_out_of_stock_inactive(self):
        from .models import Reward, Redemption, PointTransaction
        expensive = Reward.objects.create(name='Expensive', points_required=101, stock=2)
        empty = Reward.objects.create(name='Empty', points_required=10, stock=0)
        inactive = Reward.objects.create(name='Inactive', points_required=10, stock=2, is_active=False)
        self.client.force_authenticate(self.student)
        for reward, expected in [(expensive, 400), (empty, 400), (inactive, 404)]:
            self.assertEqual(self.client.post(reverse('api-redeem-reward'), {'reward_id': reward.pk}, format='json').status_code, expected)
        self.assertEqual(self.balance(), 100)
        self.assertEqual(PointTransaction.objects.filter(student=self.student).count(), 1)
        self.assertFalse(Redemption.objects.exists())

    def test_student_points_and_history_reflect_admin_refund(self):
        redemption = self.redeem()
        self.assertEqual(self.transition(redemption, 'rejected').status_code, 200)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get(reverse('student-points')).data['total_points'], 100)
        self.assertEqual(self.client.get(reverse('api-my-redemptions')).data[0]['status'], 'rejected')
        self.assertEqual(self.client.get(reverse('api-rewards')).data[0]['stock'], 3)


class MyLearningTests(TestCase):
    sections = {'continue_learning', 'courses', 'stats', 'completed_courses', 'certificates'}
    card_fields = {'enrollment_id', 'enrollment_status', 'enrolled_at', 'completed_at', 'course',
                   'progress_percentage', 'completed_lessons', 'total_lessons', 'is_completed',
                   'next_lesson', 'resume_url', 'last_learning_activity'}

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.student = self.user('LearningStudent', 'student')
        self.other = self.user('LearningOther', 'student')
        self.teacher = self.user('LearningTeacher', 'instructor')
        self.course, self.enrollment = self.enroll('Learning course')
        self.lessons = [Lesson.objects.create(course=self.course, title=f'Lesson {i}',
            content_type='video', order=i) for i in range(1, 4)]
        self.client.force_authenticate(self.student)
        self.url = reverse('api-my-learning')

    def user(self, name, role, **fields):
        return User.objects.create_user(email=f'{name.lower()}@example.com', name=name,
            role=Role.objects.get(name=role), **fields)

    def enroll(self, title, student=None, status='active', published=True):
        course = Course.objects.create(title=title, instructor=self.teacher, course_type='skill', is_published=published)
        enrollment = Enrollment.objects.create(student=student or self.student, course=course, status=status)
        return course, enrollment

    def progress(self, lesson, student=None, completed=True, when=None, enrollment=None):
        return LessonProgress.objects.create(student=student or self.student, lesson=lesson,
            enrollment=enrollment, is_completed=completed, completed_at=when if when is not None else timezone.now())

    def feed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.data

    def cards(self, data):
        return ([data['continue_learning']] if data['continue_learning'] else []) + data['courses'] + data['completed_courses']

    def test_structure_first_lesson_and_safe_course_fields(self):
        data = self.feed()
        self.assertEqual(set(data), self.sections)
        card = data['continue_learning']
        self.assertEqual(set(card), self.card_fields)
        self.assertEqual(set(card['course']), set(CourseSerializer(self.course).data))
        self.assertEqual(card['next_lesson'], {'id': self.lessons[0].pk, 'title': 'Lesson 1',
            'content_type': 'video', 'order': 1, 'lesson_number': 1})
        self.assertEqual(card['resume_url'], 'http://testserver' + reverse('api-lesson-detail', kwargs={'pk': self.lessons[0].pk}))
        self.assertEqual(self.client.get(card['resume_url']).status_code, 200)
        self.assertIsNone(card['last_learning_activity'])
        self.assertEqual(data['courses'], [])
        self.assertFalse({'email', 'password', 'verification_status', 'phone_number', 'payment_reference', 'amount_paid'} & set(card))

    def test_empty_learning_returns_null_continue_and_empty_sections(self):
        self.enrollment.delete()
        data = self.feed()
        self.assertIsNone(data['continue_learning'])
        for section in ['courses', 'completed_courses', 'certificates']:
            self.assertEqual(data[section], [])
        self.assertEqual(data['stats'], {'courses_completed': 0, 'day_streak': 0, 'hours_learned': None})

    def test_partial_progress_matches_existing_progress_endpoint(self):
        self.progress(self.lessons[0])
        self.progress(self.lessons[2], completed=False)
        self.progress(self.lessons[1], student=self.other)
        card = self.feed()['continue_learning']
        self.assertEqual(card['completed_lessons'], 1)
        self.assertEqual(card['total_lessons'], 3)
        self.assertEqual(card['progress_percentage'], 33.33)
        self.assertFalse(card['is_completed'])
        self.assertEqual(card['next_lesson']['id'], self.lessons[1].pk)
        response = self.client.get(reverse('api-course-progress', kwargs={'course_id': self.course.pk}))
        self.assertEqual(response.status_code, 200)
        for field in ['completed_lessons', 'total_lessons', 'progress_percentage', 'is_completed']:
            self.assertEqual(card[field], response.data[field])

    def test_out_of_order_completion_resumes_first_gap_with_actual_ordinal(self):
        self.progress(self.lessons[2])
        card = self.feed()['continue_learning']
        self.assertEqual(card['next_lesson']['id'], self.lessons[0].pk)
        self.assertEqual(card['next_lesson']['lesson_number'], 1)
        self.progress(self.lessons[0])
        self.assertEqual(self.feed()['continue_learning']['next_lesson']['lesson_number'], 2)

    def test_lesson_order_ties_use_existing_title_order_and_stable_id(self):
        Lesson.objects.filter(course=self.course).delete()
        z = Lesson.objects.create(course=self.course, title='Z', order=0, content_type='text')
        a = Lesson.objects.create(course=self.course, title='A', order=0, content_type='text')
        duplicate = Lesson.objects.create(course=self.course, title='A', order=0, content_type='text')
        self.assertEqual(self.feed()['continue_learning']['next_lesson']['id'], a.pk)
        self.progress(a)
        self.assertEqual(self.feed()['continue_learning']['next_lesson']['id'], duplicate.pk)
        self.progress(duplicate)
        card = self.feed()['continue_learning']
        self.assertEqual(card['next_lesson']['id'], z.pk)
        self.assertEqual(card['next_lesson']['lesson_number'], 3)

    def test_zero_lesson_course_is_not_completed_or_resumable(self):
        self.enrollment.delete()
        empty, _ = self.enroll('No lessons')
        data = self.feed()
        self.assertIsNone(data['continue_learning'])
        card = data['courses'][0]
        self.assertEqual(card['course']['id'], empty.pk)
        self.assertEqual(card['progress_percentage'], 0)
        self.assertEqual(card['completed_lessons'], 0)
        self.assertEqual(card['total_lessons'], 0)
        self.assertFalse(card['is_completed'])
        self.assertIsNone(card['next_lesson'])
        self.assertIsNone(card['resume_url'])
        self.assertEqual(data['stats']['courses_completed'], 0)

    def test_completed_courses_transition_once_and_have_no_resume(self):
        for lesson in self.lessons:
            self.progress(lesson)
        data = self.feed()
        self.assertIsNone(data['continue_learning'])
        self.assertEqual(data['courses'], [])
        card = data['completed_courses'][0]
        self.assertEqual(card['progress_percentage'], 100)
        self.assertTrue(card['is_completed'])
        self.assertEqual(card['enrollment_status'], 'completed')
        self.assertIsNone(card['next_lesson'])
        self.assertIsNone(card['resume_url'])
        self.enrollment.refresh_from_db()
        completed_at = self.enrollment.completed_at
        self.assertEqual(self.enrollment.status, 'completed')
        self.assertIsNotNone(completed_at)
        self.feed()
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.completed_at, completed_at)
        self.assertEqual(data['stats']['courses_completed'], 1)

    def test_historical_completed_status_retained_if_curriculum_changes(self):
        self.enrollment.status = 'completed'
        self.enrollment.completed_at = timezone.now() - timedelta(days=1)
        self.enrollment.save()
        data = self.feed()
        self.assertEqual(data['completed_courses'][0]['enrollment_status'], 'completed')
        self.assertEqual(data['completed_courses'][0]['progress_percentage'], 0)
        self.assertFalse(data['completed_courses'][0]['is_completed'])
        self.assertEqual(data['stats']['courses_completed'], 1)
        self.assertIsNone(data['continue_learning'])
        self.assertEqual(self.client.get(reverse('api-course-progress', kwargs={'course_id': self.course.pk})).data['is_completed'], False)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, 'completed')

    def test_enrollment_statuses_ownership_and_private_course_access(self):
        pending, pending_enrollment = self.enroll('Pending', status='pending_payment')
        cancelled, cancelled_enrollment = self.enroll('Cancelled', status='cancelled')
        friend, _ = self.enroll('Friend private', student=self.other, published=False)
        private, _ = self.enroll('My unpublished', published=False)
        self.progress(Lesson.objects.create(course=friend, title='Other lesson', content_type='text'), student=self.other)
        data = self.feed()
        ids = {card['course']['id'] for card in self.cards(data)}
        self.assertEqual(ids, {self.course.pk, private.pk})
        self.assertFalse({pending.pk, cancelled.pk, friend.pk} & ids)
        self.assertEqual(self.client.get(reverse('api-course-progress', kwargs={'course_id': private.pk})).status_code, 200)
        pending_enrollment.refresh_from_db()
        cancelled_enrollment.refresh_from_db()
        self.assertEqual(pending_enrollment.status, 'pending_payment')
        self.assertEqual(cancelled_enrollment.status, 'cancelled')

    def test_ownership_fields_cannot_override_user(self):
        for field in ['student', 'student_id', 'user', 'user_id']:
            with self.subTest(field=field):
                self.assertEqual(self.client.get(self.url, {field: self.other.pk}).status_code, 400)
                self.assertEqual(self.client.generic('GET', self.url,
                    json.dumps({field: self.other.pk}), content_type='application/json').status_code, 400)
        card = self.feed()['continue_learning']
        self.assertEqual(card['enrollment_id'], self.enrollment.pk)

    def test_continue_selection_uses_recent_real_activity_then_enrollment_and_stable_id(self):
        recent, recent_enrollment = self.enroll('Recent enrollment')
        Lesson.objects.create(course=recent, title='Recent lesson', content_type='text')
        self.assertEqual(self.feed()['continue_learning']['course']['id'], recent.pk)
        moment = timezone.now() - timedelta(days=1)
        self.progress(self.lessons[0], when=moment)
        self.assertEqual(self.feed()['continue_learning']['course']['id'], self.course.pk)
        # Someone else's recent progress must not affect my continue card.
        recent_lesson = recent.lessons.first()
        self.progress(recent_lesson, student=self.other)
        self.assertEqual(self.feed()['continue_learning']['course']['id'], self.course.pk)
        Enrollment.objects.filter(pk=recent_enrollment.pk).update(enrolled_at=self.enrollment.enrolled_at)
        LessonProgress.objects.filter(student=self.student).delete()
        self.assertEqual(self.feed()['continue_learning']['course']['id'], recent.pk)
        self.assertEqual(self.feed()['continue_learning']['course']['id'], recent.pk)

    def test_quiz_completion_activity_used_but_unfinished_quizzes_ignored(self):
        from .models import Quiz, QuizAttempt
        other_course, other_enrollment = self.enroll('Quiz course')
        Lesson.objects.create(course=other_course, title='Resume', content_type='video')
        moment = timezone.now() - timedelta(hours=2)
        self.progress(self.lessons[0], when=moment)
        quiz = Quiz.objects.create(course=other_course, title='Quiz')
        attempt = QuizAttempt.objects.create(student=self.student, enrollment=other_enrollment, quiz=quiz)
        self.assertEqual(self.feed()['continue_learning']['course']['id'], self.course.pk)
        attempt.completed_at = moment + timedelta(hours=1)
        attempt.save()
        card = self.feed()['continue_learning']
        self.assertEqual(card['course']['id'], other_course.pk)
        self.assertEqual(card['last_learning_activity'], attempt.completed_at.isoformat().replace('+00:00', 'Z'))

    def test_missing_completion_timestamp_is_not_fabricated(self):
        self.progress(self.lessons[0])
        LessonProgress.objects.filter(student=self.student).update(completed_at=None)
        card = self.feed()['continue_learning']
        self.assertEqual(card['completed_lessons'], 1)
        self.assertIsNone(card['last_learning_activity'])
        self.assertNotIn('last_accessed', card)
        self.assertNotIn('playback_position', card)

    def test_stats_use_existing_streak_and_hours_unavailable(self):
        from .models import LearningStreak, StreakHistory
        streak = LearningStreak.objects.create(student=self.student, current_streak=4,
            longest_streak=8, last_active_date=timezone.now().date() - timedelta(days=3))
        LearningStreak.objects.create(student=self.other, current_streak=99)
        stats = self.feed()['stats']
        self.assertEqual(stats['day_streak'], 4)
        self.assertEqual(stats['day_streak'], self.client.get(reverse('api-my-streak')).data['current_streak'])
        self.assertIsNone(stats['hours_learned'])
        streak.refresh_from_db()
        self.assertEqual(streak.current_streak, 4)
        self.assertFalse(StreakHistory.objects.filter(student=self.student).exists())

    def test_certificates_reuse_existing_serializer_and_student_scope(self):
        from .models import Certificate
        own = Certificate.objects.create(student=self.student, course=self.course, certificate_type='course')
        grade = Grade.objects.first()
        own_grade = Certificate.objects.create(student=self.student, grade=grade, certificate_type='grade')
        Certificate.objects.create(student=self.other, course=self.course, certificate_type='course')
        certificates = self.feed()['certificates']
        self.assertEqual({c['id'] for c in certificates}, {own.pk, own_grade.pk})
        self.assertEqual(certificates, self.client.get(reverse('api-my-certificates')).data)
        self.assertTrue(all(set(c) <= {'id', 'certificate_type', 'course', 'course_title', 'grade', 'grade_name', 'issued_at'} for c in certificates))

    def test_no_duplicate_courses_across_sections(self):
        for index in range(3):
            course, _ = self.enroll(f'Extra course {index}')
            lesson = Lesson.objects.create(course=course, title='Lesson', content_type='text')
            if index == 2:
                self.progress(lesson)
        data = self.feed()
        cards = self.cards(data)
        ids = [card['course']['id'] for card in cards]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(data['stats']['courses_completed'], 1)

    def test_read_query_count_constant_for_many_courses_lessons_and_certificates(self):
        from .models import Certificate
        self.progress(self.lessons[0])
        Certificate.objects.create(student=self.student, course=self.course, certificate_type='course')
        with self.assertNumQueries(7):
            self.feed()
        for index in range(8):
            course, enrollment = self.enroll(f'Bulk course {index}')
            for order in range(3):
                lesson = Lesson.objects.create(course=course, title=f'Lesson {order}', order=order, content_type='text')
                if order == 0:
                    self.progress(lesson, enrollment=enrollment)
            Certificate.objects.create(student=self.student, course=course, certificate_type='course')
        with self.assertNumQueries(7):
            data = self.feed()
        self.assertEqual(len(self.cards(data)), 9)
        self.assertEqual(len(data['certificates']), 9)

    def test_authentication_roles_inactive_and_read_only(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        for user in [self.teacher, self.user('LearningAdmin', 'super_admin'),
                     self.user('LearningInactive', 'student', is_active=False)]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(self.student)
        for method in ['post', 'patch', 'delete']:
            self.assertEqual(getattr(self.client, method)(self.url).status_code, 405)
        from rest_framework_simplejwt.tokens import RefreshToken
        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.student).access_token}')
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.student.email_verified = False
        self.student.save()
        self.assertEqual(self.client.get(self.url).status_code, 401)


class LearningCompatibilityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.student = User.objects.create_user(email='compat-student@example.com', role=Role.objects.get(name='student'))
        self.teacher = User.objects.create_user(email='compat-teacher@example.com', role=Role.objects.get(name='instructor'))
        self.course = Course.objects.create(title='Compatibility course', course_type='skill', instructor=self.teacher, is_published=True)
        self.lesson = Lesson.objects.create(course=self.course, title='Complete', content_type='text')
        self.client.force_authenticate(self.student)

    def test_enrollment_completion_and_progress_preserve_existing_contract(self):
        self.assertEqual(self.client.post(reverse('api-enroll-course', kwargs={'course_id': self.course.pk})).status_code, 201)
        self.assertEqual(self.client.post(reverse('api-complete-lesson', kwargs={'lesson_id': self.lesson.pk})).status_code, 200)
        url = reverse('api-course-progress', kwargs={'course_id': self.course.pk})
        response = self.client.get(url)
        self.assertEqual(response.data, {'course_id': self.course.pk, 'total_lessons': 1,
            'completed_lessons': 1, 'progress_percentage': 100.0, 'is_completed': True})
        enrollment = Enrollment.objects.get(student=self.student, course=self.course)
        completed_at = enrollment.completed_at
        self.client.get(url)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.completed_at, completed_at)
        self.assertEqual(self.client.get(reverse('api-my-enrollments')).data[0]['status'], 'completed')

    def test_streak_completion_is_once_per_day_and_preserves_grace_rules(self):
        from .models import LearningStreak, StreakSettings, StreakHistory
        Enrollment.objects.create(student=self.student, course=self.course)
        settings = StreakSettings.get_solo()
        settings.grace_period_days = 1
        settings.save()
        today = timezone.now().date()
        LearningStreak.objects.create(student=self.student, current_streak=3, longest_streak=3,
            last_active_date=today - timedelta(days=2))
        url = reverse('api-complete-lesson', kwargs={'lesson_id': self.lesson.pk})
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.get(reverse('api-my-streak')).data['current_streak'], 4)
        self.assertEqual(StreakHistory.objects.filter(student=self.student).count(), 1)
        data = self.client.get(reverse('api-my-learning')).data
        self.assertEqual(data['stats']['day_streak'], 4)
        self.assertEqual(data['stats']['courses_completed'], 1)

    def test_existing_course_certificate_requires_completion_and_quiz_pass(self):
        from .models import Certificate, CertificateCriteria, Quiz, QuizAttempt
        enrollment = Enrollment.objects.create(student=self.student, course=self.course)
        criteria = CertificateCriteria.get_solo()
        criteria.skill_course_requires_quiz_pass = True
        criteria.save()
        quiz = Quiz.objects.create(course=self.course, title='Required quiz', is_published=True)
        url = reverse('api-check-course-certificate', kwargs={'course_id': self.course.pk})
        self.assertEqual(self.client.post(url).status_code, 400)
        self.client.post(reverse('api-complete-lesson', kwargs={'lesson_id': self.lesson.pk}))
        self.client.get(reverse('api-my-learning'))
        self.assertEqual(self.client.post(url).status_code, 400)
        QuizAttempt.objects.create(student=self.student, quiz=quiz, enrollment=enrollment, is_passed=True, completed_at=timezone.now())
        issued = self.client.post(url)
        self.assertEqual(issued.status_code, 201)
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(Certificate.objects.filter(student=self.student).count(), 1)
        self.assertEqual(self.client.get(reverse('api-my-learning')).data['certificates'][0], issued.data)


class HomeFeedTests(TestCase):
    sections = {'featured_courses', 'recommended_courses', 'skill_courses',
                'events', 'advertisements', 'top_instructors'}

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.student = self.user('HomeStudent', 'student')
        self.profile = StudentProfile.objects.create(user=self.student)
        self.teacher = self.user('HomeTeacher')
        InstructorProfile.objects.create(user=self.teacher, qualification='MSc')
        self.course = self.course_for('Coding basics')
        self.client.force_authenticate(self.student)
        self.url = reverse('api-home')

    def user(self, name, role='instructor', **fields):
        return User.objects.create_user(email=f'{name.lower()}@example.com', name=name,
            role=Role.objects.get(name=role), verification_status='verified', **fields)

    def course_for(self, title, **fields):
        fields.setdefault('instructor', self.teacher)
        fields.setdefault('course_type', 'skill')
        fields.setdefault('is_published', True)
        return Course.objects.create(title=title, **fields)

    def event(self, title='ICT & AI Bootcamp', **fields):
        from .models import Event
        fields.setdefault('host', self.teacher)
        fields.setdefault('is_published', True)
        fields.setdefault('start_at', timezone.now() + timedelta(days=1))
        fields.setdefault('end_at', timezone.now() + timedelta(days=2))
        return Event.objects.create(title=title, **fields)

    def ad(self, **fields):
        from .models import Advertisement
        fields.setdefault('title', 'Admin-managed advertisement')
        fields.setdefault('banner_image', 'advertisements/home.png')
        fields.setdefault('is_active', True)
        return Advertisement.objects.create(**fields)

    def feed(self):
        # Exercise the normal request query cost even when fixture construction
        # or a preceding request cached the reverse profile on this User object.
        self.student._state.fields_cache.pop('student_profile', None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_endpoint_sections_and_course_serializer_reuse(self):
        data = self.feed()
        self.assertEqual(set(data), self.sections)
        self.assertTrue(all(isinstance(value, list) for value in data.values()))
        card = data['featured_courses'][0]
        self.assertEqual(set(card), set(CourseSerializer(self.course).data) | {'is_enrolled'})
        self.assertFalse(card['is_enrolled'])
        self.assertEqual(card['id'], self.course.pk)

    def test_empty_feed_returns_empty_arrays(self):
        self.course.delete()
        self.assertEqual(self.feed(), {section: [] for section in self.sections})

    def test_publication_and_skill_type_rules(self):
        draft = self.course_for('Private draft', is_published=False)
        academic = self.course_for('Academic', course_type='academic')
        data = self.feed()
        for section in ['featured_courses', 'recommended_courses', 'skill_courses']:
            self.assertNotIn(draft.pk, [row['id'] for row in data[section]])
            self.assertTrue(all(row['is_published'] for row in data[section]))
        self.assertIn(academic.pk, [row['id'] for row in data['featured_courses']])
        self.assertEqual([row['id'] for row in data['skill_courses']], [self.course.pk])

    def test_featured_ranking_and_live_review_statistics(self):
        low = self.course_for('Lower rated')
        tie = self.course_for('More reviews')
        unrated = self.course_for('No reviews')
        other = self.user('HomeOther', 'student')
        review = CourseReview.objects.create(student=self.student, course=self.course, rating=5)
        CourseReview.objects.create(student=self.student, course=low, rating=2)
        for student in [self.student, other]:
            CourseReview.objects.create(student=student, course=tie, rating=5)
        rows = self.feed()['featured_courses']
        self.assertEqual([row['id'] for row in rows], [tie.pk, self.course.pk, low.pk, unrated.pk])
        self.assertEqual(rows[0]['average_rating'], 5)
        self.assertEqual(rows[0]['review_count'], 2)
        review.rating = 1
        review.save()
        self.assertEqual([r['id'] for r in self.feed()['featured_courses']], [tie.pk, low.pk, self.course.pk, unrated.pk])
        review.delete()
        row = next(r for r in self.feed()['featured_courses'] if r['id'] == self.course.pk)
        self.assertIsNone(row['average_rating'])
        self.assertEqual(row['review_count'], 0)

    def test_personalization_by_literal_interests_and_subject(self):
        from .models import LearningInterest, Subject
        self.profile.learning_interests.add(LearningInterest.objects.get(slug='coding'))
        generic = self.course_for('New generic course')
        self.assertEqual(self.feed()['recommended_courses'][0]['id'], self.course.pk)
        self.profile.learning_interests.set([LearningInterest.objects.get(slug='mathematics')])
        math = self.course_for('Algebra', course_type='academic', subject=Subject.objects.create(name='Mathematics'))
        self.course_for('Newest generic course')
        self.assertEqual(self.feed()['recommended_courses'][0]['id'], math.pk)
        self.assertIn(generic.pk, [r['id'] for r in self.feed()['recommended_courses']])

    def test_inactive_interests_do_not_personalize(self):
        from .models import LearningInterest
        interest = LearningInterest.objects.get(slug='coding')
        interest.is_active = False
        interest.save()
        self.profile.learning_interests.add(interest)
        newest = self.course_for('New unrelated course')
        self.assertEqual(self.feed()['recommended_courses'][0]['id'], newest.pk)

    def test_grade_recommendations_exclude_other_grades(self):
        self.profile.grade = Grade.objects.first()
        self.profile.save()
        matched = self.course_for('Grade matched', course_type='academic', grade=self.profile.grade)
        other_grade = Grade.objects.create(name='Home other grade')
        wrong = self.course_for('Wrong grade', course_type='academic', grade=other_grade)
        generic = self.course_for('Recent skill')
        rows = self.feed()['recommended_courses']
        self.assertEqual(rows[0]['id'], matched.pk)
        self.assertNotIn(wrong.pk, [r['id'] for r in rows])
        self.assertIn(generic.pk, [r['id'] for r in rows])

    def test_fallback_deterministic_without_profile_and_without_matches(self):
        from .models import LearningInterest
        recent = self.course_for('Recent unrelated')
        expected = [recent.pk, self.course.pk]
        self.assertEqual([r['id'] for r in self.feed()['recommended_courses']], expected)
        self.profile.learning_interests.add(LearningInterest.objects.get(slug='robotics'))
        self.assertEqual([r['id'] for r in self.feed()['recommended_courses']], expected)
        self.profile.delete()
        self.assertEqual([r['id'] for r in self.feed()['recommended_courses']], expected)
        self.assertEqual([r['id'] for r in self.feed()['recommended_courses']], expected)
        # A timestamp tie has a stable unique-ID tie-breaker.
        Course.objects.filter(pk=recent.pk).update(created_at=self.course.created_at)
        self.assertEqual([r['id'] for r in self.feed()['recommended_courses']], [self.course.pk, recent.pk])

    def test_enrollment_state_and_recommendation_exclusions(self):
        cancelled = self.course_for('Cancelled course')
        Enrollment.objects.create(student=self.student, course=cancelled, status='cancelled')
        courses = []
        for state in ['active', 'completed', 'pending_payment']:
            course = self.course_for(state)
            Enrollment.objects.create(student=self.student, course=course, status=state)
            courses.append(course)
        data = self.feed()
        recommendations = {r['id'] for r in data['recommended_courses']}
        self.assertTrue({self.course.pk, cancelled.pk}.issubset(recommendations))
        self.assertFalse({c.pk for c in courses} & recommendations)
        cards = {r['id']: r for r in data['featured_courses']}
        self.assertTrue(cards[courses[0].pk]['is_enrolled'])
        self.assertTrue(cards[courses[1].pk]['is_enrolled'])
        self.assertFalse(cards[courses[2].pk]['is_enrolled'])
        Enrollment.objects.create(student=self.user('EnrolledOther', 'student'), course=self.course)
        self.assertFalse(next(r for r in self.feed()['featured_courses'] if r['id'] == self.course.pk)['is_enrolled'])

    def test_advertisement_rules_and_exact_existing_api_representation(self):
        now = timezone.now()
        with patch('core.api_views.timezone.now', return_value=now):
            visible = self.ad(starts_at=now, ends_at=now)
            self.ad(is_active=False)
            self.ad(archived_at=now)
            self.ad(starts_at=now + timedelta(seconds=1))
            self.ad(ends_at=now - timedelta(seconds=1))
            evergreen = self.ad(display_order=1)
            ads = self.feed()['advertisements']
            self.assertEqual([a['id'] for a in ads], [visible.pk, evergreen.pk])
            response = self.client.get(reverse('api-advertisements'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(ads, response.data)
            self.assertNotIn('created_by', ads[0])

    def test_top_instructors_consistency_privacy_and_canonical_photo(self):
        self.teacher.profile_photo_url = 'profile-photos/home/image.png'
        self.teacher.save()
        pending = self.user('HomePending')
        pending.verification_status = 'pending'
        pending.save()
        self.course_for('Pending teacher', instructor=pending)
        empty = self.user('HomeEmpty')
        inactive = self.user('HomeInactive', is_active=False)
        self.course_for('Inactive teacher', instructor=inactive)
        CourseReview.objects.create(student=self.student, course=self.course, rating=4)
        instructors = self.feed()['top_instructors']
        self.assertEqual(instructors, self.client.get(reverse('api-top-instructors')).data)
        self.assertEqual([row['id'] for row in instructors], [self.teacher.pk])
        self.assertEqual(instructors[0]['average_rating'], 4)
        self.assertEqual(instructors[0]['review_count'], 1)
        self.assertEqual(instructors[0]['profile_photo_url'], 'http://testserver/media/profile-photos/home/image.png')
        self.assertEqual(set(instructors[0]), PublicInstructorTests.fields)
        self.assertNotIn(empty.pk, [row['id'] for row in instructors])

    def test_event_visibility_order_viewer_state_and_existing_serializer(self):
        from .models import EventBookmark, EventRegistration
        now = timezone.now()
        later = self.event()
        ongoing = self.event('Ongoing', start_at=now - timedelta(hours=1), end_at=now)
        self.event('Hidden', is_published=False)
        self.event('Ended', start_at=now - timedelta(days=2), end_at=now - timedelta(seconds=1))
        EventRegistration.objects.create(event=ongoing, user=self.student, status='registered')
        EventBookmark.objects.create(event=ongoing, user=self.student)
        with patch('core.api_views.timezone.now', return_value=now):
            events = self.feed()['events']
            self.assertEqual([e['id'] for e in events], [ongoing.pk, later.pk])
            self.assertEqual(events[0]['my_status'], 'registered')
            self.assertTrue(events[0]['is_saved'])
            self.assertEqual(events[0]['attendee_count'], 1)
            self.assertIsNone(events[0]['rating'])
            self.assertEqual(events[0], self.client.get(reverse('api-event-detail', kwargs={'event_id': ongoing.pk})).data)
        self.assertEqual(set(events[0]['host']), {'id', 'name', 'role', 'avatar_url'})

    def test_all_section_limits_and_query_count_independent_of_items(self):
        self.event()
        self.ad()
        with CaptureQueriesContext(connection) as initial:
            self.feed()
        self.assertLessEqual(len(initial), 12)
        for index in range(10):
            teacher = self.user(f'HomeExtra{index}')
            self.course_for(f'Course {index}', instructor=teacher)
            self.event(f'Event {index}')
            self.ad(title=f'Ad {index}')
        with CaptureQueriesContext(connection) as expanded:
            data = self.feed()
        self.assertEqual(len(expanded), len(initial))
        for section, limit in [('featured_courses', 6), ('recommended_courses', 6),
                               ('skill_courses', 6), ('events', 3),
                               ('advertisements', 3), ('top_instructors', 6)]:
            self.assertEqual(len(data[section]), limit)
        self.assertEqual(data['top_instructors'], self.client.get(reverse('api-top-instructors')).data[:6])

    def test_home_never_calls_external_ai_and_existing_ai_pool_still_works(self):
        self.course_for('Draft', is_published=False)
        with patch('core.ai_service.GeminiService._get_client', side_effect=AssertionError('Home must not call Gemini')):
            self.feed()
        with patch('core.ai_service.GeminiService.recommend_learning_content', return_value={
            'courses': [{'id': self.course.pk, 'reason': 'Relevant'}], 'lessons': [], 'videos': [],
        }) as recommend:
            response = self.client.post(reverse('ai-recommendations'), {'learning_goal': 'Coding'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([c.pk for c in recommend.call_args.kwargs['courses']], [self.course.pk])
        self.assertEqual(response.data['recommendations']['courses'][0]['id'], self.course.pk)

    def test_authentication_student_only_and_read_only(self):
        for user in [self.teacher, self.user('HomeAdmin', 'super_admin'),
                     self.user('HomeInactiveStudent', 'student', is_active=False)]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.force_authenticate(self.student)
        for method in ['post', 'patch', 'delete']:
            self.assertEqual(getattr(self.client, method)(self.url).status_code, 405)
        from rest_framework_simplejwt.tokens import RefreshToken
        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.student).access_token}')
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.student.email_verified = False
        self.student.save()
        self.assertEqual(self.client.get(self.url).status_code, 401)


class PublicInstructorTests(TestCase):
    fields = {'id', 'name', 'profile_photo_url', 'qualification', 'subject_expertise',
              'average_rating', 'review_count', 'total_students', 'total_courses'}

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.student = self.user('Student', 'student')
        self.other = self.user('Other', 'student')
        self.teacher = self.user('Teacher')
        InstructorProfile.objects.create(user=self.teacher, qualification='MSc', subject_expertise='Python')
        self.course = self.course_for(self.teacher)
        self.url = reverse('api-top-instructors')
        self.client.force_authenticate(self.student)

    def user(self, name, role='instructor', **kwargs):
        return User.objects.create_user(email=f'{name.lower()}@example.com', name=name,
            role=Role.objects.get(name=role), verification_status='verified', **kwargs)

    def course_for(self, teacher, published=True):
        return Course.objects.create(instructor=teacher, title='Python', course_type='skill', is_published=published)

    def detail(self, teacher=None):
        return self.client.get(reverse('api-public-instructor-detail',
            kwargs={'instructor_id': (teacher or self.teacher).pk}))

    def ids(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return [row['id'] for row in response.data]

    def review(self, course, student, rating):
        return CourseReview.objects.create(course=course, student=student, rating=rating)

    def test_approved_instructor_and_empty_statistics(self):
        self.assertEqual(self.ids(), [self.teacher.pk])
        data = self.detail().data
        self.assertIsNone(data['average_rating'])
        self.assertEqual(data['review_count'], 0)
        self.assertEqual(data['total_students'], 0)
        self.assertEqual(data['total_courses'], 1)

    def test_nonpublic_instructors_hidden_for_all_roles(self):
        hidden = []
        for state in ['pending', 'rejected', 'not_applicable']:
            teacher = self.user(state)
            teacher.verification_status = state
            teacher.save()
            self.course_for(teacher)
            hidden.append(teacher)
        inactive = self.user('Inactive', is_active=False)
        self.course_for(inactive)
        hidden.append(inactive)
        nonteacher = self.user('Nonteacher', 'student')
        self.course_for(nonteacher)
        hidden.append(nonteacher)
        for viewer in [self.student, self.teacher, self.user('Admin', 'super_admin')]:
            self.client.force_authenticate(viewer)
            self.assertEqual(self.ids(), [self.teacher.pk])
            for teacher in hidden:
                self.assertEqual(self.detail(teacher).status_code, 404)

    def test_no_public_courses_hidden_and_missing_profile_supported(self):
        empty = self.user('Empty')
        draft = self.user('Draft')
        self.course_for(draft, False)
        for teacher in [empty, draft]:
            self.assertEqual(self.detail(teacher).status_code, 404)
        self.assertEqual(self.ids(), [self.teacher.pk])
        self.course_for(empty)
        self.assertEqual(self.detail(empty).data['qualification'], '')
        self.assertEqual(self.detail(empty).data['subject_expertise'], '')
        self.assertEqual(self.detail(self.user('Missing')).status_code, 404)

    def test_distinct_students_public_courses_and_valid_statuses(self):
        second = self.course_for(self.teacher)
        draft = self.course_for(self.teacher, False)
        for course in [self.course, second]:
            Enrollment.objects.create(student=self.student, course=course, status='active')
        Enrollment.objects.create(student=self.other, course=second, status='completed')
        for name, state, course in [('Pending', 'pending_payment', second),
                                   ('Cancelled', 'cancelled', second), ('Draftstudent', 'active', draft)]:
            Enrollment.objects.create(student=self.user(name, 'student'), course=course, status=state)
        unrelated = self.course_for(self.user('Unrelated'))
        Enrollment.objects.create(student=self.user('Unrelatedstudent', 'student'), course=unrelated)
        data = self.detail().data
        self.assertEqual(data['total_students'], 2)
        self.assertEqual(data['total_courses'], 2)
        self.assertEqual({c['id'] for c in data['courses']}, {self.course.pk, second.pk})
        self.assertTrue(all(c['is_published'] for c in data['courses']))
        row = next(row for row in self.client.get(self.url).data if row['id'] == self.teacher.pk)
        self.assertEqual(row['total_students'], 2)
        self.assertEqual(row['total_courses'], 2)

    def test_review_weighted_average_and_no_enrollment_join_bias(self):
        second = self.course_for(self.teacher)
        self.review(self.course, self.student, 1)
        self.review(self.course, self.other, 5)
        self.review(second, self.student, 3)
        for student in [self.student, self.other, self.user('Third', 'student')]:
            Enrollment.objects.create(student=student, course=self.course)
        data = self.detail().data
        self.assertEqual(data['review_count'], 3)
        self.assertEqual(data['average_rating'], 3)
        self.review(second, self.other, 5)
        data = self.detail().data
        self.assertEqual(data['review_count'], 4)
        self.assertEqual(data['average_rating'], 3.5)
        self.assertEqual(self.client.get(self.url).data[0]['average_rating'], 3.5)

    def test_historical_reviews_follow_existing_aggregate_policy(self):
        draft = self.course_for(self.teacher, False)
        self.review(draft, self.student, 5)
        self.review(self.course, self.other, 1)
        data = self.detail().data
        self.assertEqual(data['average_rating'], 3)
        self.assertEqual(data['review_count'], 2)
        self.assertEqual(data['total_courses'], 1)
        self.assertEqual([c['id'] for c in data['courses']], [self.course.pk])

    def test_review_api_updates_and_deletions_change_instructor_statistics(self):
        Enrollment.objects.create(student=self.student, course=self.course)
        url = reverse('api-course-reviews', kwargs={'course_id': self.course.pk})
        me = reverse('api-my-course-review', kwargs={'course_id': self.course.pk})
        self.assertEqual(self.client.post(url, {'rating': 2}, format='json').status_code, 201)
        self.assertEqual(self.detail().data['average_rating'], 2)
        self.assertEqual(self.client.patch(me, {'rating': 5}, format='json').status_code, 200)
        self.assertEqual(self.client.get(self.url).data[0]['average_rating'], 5)
        self.assertEqual(self.client.delete(me).status_code, 204)
        self.assertIsNone(self.detail().data['average_rating'])
        self.assertEqual(self.detail().data['review_count'], 0)

    def test_ranking_each_tie_breaker_and_stable_id(self):
        # Each adjacent pair isolates one ranking criterion.
        specs = [('High', [5], 1, 1), ('Reviews', [4, 4], 1, 1),
                 ('Students', [4], 2, 1), ('Courses', [4], 1, 2),
                 ('Stablefirst', [4], 1, 1), ('Stablesecond', [4], 1, 1)]
        expected = []
        for name, ratings, student_count, course_count in specs:
            teacher = self.user(name)
            courses = [self.course_for(teacher) for _ in range(course_count)]
            for index, rating in enumerate(ratings):
                self.review(courses[0], [self.student, self.other][index], rating)
            for student in [self.student, self.other][:student_count]:
                Enrollment.objects.create(student=student, course=courses[0])
            expected.append(teacher.pk)
        expected.append(self.teacher.pk)  # Unrated instructors sort last.
        self.assertEqual(self.ids(), expected)
        self.assertEqual(self.ids(), expected)

    def test_privacy_and_reuse_course_serializer(self):
        data = self.detail().data
        self.assertEqual(set(data), self.fields | {'courses'})
        self.assertEqual(set(self.client.get(self.url).data[0]), self.fields)
        self.assertEqual(data['qualification'], 'MSc')
        self.assertEqual(data['subject_expertise'], 'Python')
        self.assertEqual(set(data['courses'][0]), set(CourseSerializer(self.course).data))
        private = {'email', 'password', 'phone_number', 'verification_documents',
                   'cv_resume_document', 'verified_by', 'verified_at', 'verification_status',
                   'is_staff', 'dob', 'location', 'created_at', 'updated_at'}
        self.assertFalse(private & set(data))

    def test_query_counts_do_not_grow_with_instructors_or_courses(self):
        with self.assertNumQueries(1):
            self.assertEqual(self.client.get(self.url).status_code, 200)
        with self.assertNumQueries(2):
            self.assertEqual(self.detail().status_code, 200)
        for index in range(5):
            teacher = self.user(f'Extra{index}')
            self.course_for(teacher)
            self.course_for(self.teacher)
        with self.assertNumQueries(1):
            self.assertEqual(len(self.client.get(self.url).data), 6)
        with self.assertNumQueries(2):
            self.assertEqual(len(self.detail().data['courses']), 6)

    def test_public_photos_use_canonical_storage_resolution(self):
        for stored in ['profile-photos/1/new.png', '/media/profile-photos/1/old.png',
                       'https://legacy.example.com/media/profile-photos/1/legacy.png', '']:
            with self.subTest(stored=stored):
                self.teacher.profile_photo_url = stored
                self.teacher.save(update_fields=['profile_photo_url'])
                expected = ('http://testserver' + self.teacher.profile_photo_src) if stored else None
                self.assertEqual(self.detail().data['profile_photo_url'], expected)
                self.assertEqual(self.client.get(self.url).data[0]['profile_photo_url'], expected)

    def test_public_photos_preserve_storage_backend_urls(self):
        self.teacher.profile_photo_url = 'profile-photos/1/new.png'
        self.teacher.save(update_fields=['profile_photo_url'])
        signed_url = 'https://cdn.example.com/photos/new.png?signature=fresh'
        with patch('core.documents.default_storage.url', return_value=signed_url) as resolve:
            self.assertEqual(self.detail().data['profile_photo_url'], signed_url)
            resolve.assert_called_once_with('profile-photos/1/new.png')
        self.assertEqual(self.detail().data['profile_photo_url'], 'http://testserver/media/profile-photos/1/new.png')

    def test_authentication_and_read_only_endpoints(self):
        detail_url = reverse('api-public-instructor-detail', kwargs={'instructor_id': self.teacher.pk})
        for url in [self.url, detail_url]:
            self.assertEqual(self.client.post(url, {'total_students': 999}, format='json').status_code, 405)
            self.assertEqual(self.client.patch(url, {'average_rating': 5}, format='json').status_code, 405)
            self.assertEqual(self.client.delete(url).status_code, 405)
        self.client.force_authenticate(None)
        for url in [self.url, detail_url]:
            self.assertEqual(self.client.get(url).status_code, 401)
        from rest_framework_simplejwt.tokens import RefreshToken
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.student).access_token}')
        for url in [self.url, detail_url]:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.student.email_verified = False
        self.student.save()
        self.assertEqual(self.client.get(self.url).status_code, 401)


class CourseReviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.student = User.objects.create_user(email='reviewer@example.com', name='Reviewer', role=Role.objects.get(name='student'))
        self.other = User.objects.create_user(email='other-reviewer@example.com', name='Other', role=Role.objects.get(name='student'))
        self.instructor = User.objects.create_user(email='review-teacher@example.com', name='Teacher', role=Role.objects.get(name='instructor'))
        self.admin = User.objects.create_user(email='review-admin@example.com', name='Admin', role=Role.objects.get(name='super_admin'))
        self.course = Course.objects.create(title='Review course', instructor=self.instructor, course_type='skill', is_published=True)
        self.enrollment = Enrollment.objects.create(student=self.student, course=self.course)
        self.url = reverse('api-course-reviews', kwargs={'course_id': self.course.pk})
        self.me = reverse('api-my-course-review', kwargs={'course_id': self.course.pk})
        self.detail = reverse('api-course-detail', kwargs={'pk': self.course.pk})
        self.client.force_authenticate(self.student)

    def stats(self):
        return self.client.get(self.detail).data

    def test_rating_boundaries_and_optional_review(self):
        for rating in [1, 5]:
            with self.subTest(rating=rating):
                response = self.client.post(self.url, {'rating': rating}, format='json')
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.data['review'], '')
                self.assertEqual(self.client.delete(self.me).status_code, 204)
        self.assertEqual(self.client.post(self.url, {'rating': 3, 'review': ''}, format='json').status_code, 201)

    def test_invalid_ratings(self):
        for rating in [0, 6, 2.5, 2.0, True, '2.5', '2.0', 'bad', None]:
            with self.subTest(rating=rating):
                self.assertEqual(self.client.post(self.url, {'rating': rating}, format='json').status_code, 400)
        self.assertEqual(self.client.post(self.url, {}, format='json').status_code, 400)
        self.assertEqual(self.client.post(self.url, [1, 2], format='json').status_code, 400)

    def test_enrollment_rules(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.post(self.url, {'rating': 4}, format='json').status_code, 403)
        self.client.force_authenticate(self.student)
        for state in ['pending_payment', 'cancelled', 'active', 'completed']:
            self.enrollment.status = state
            self.enrollment.save()
            self.assertEqual(self.client.post(self.url, {'rating': 4}, format='json').status_code, 201 if state in ['active', 'completed'] else 403)
            CourseReview.objects.all().delete()

    def test_nonstudents_and_inactive_student(self):
        for user in [self.instructor, self.admin]:
            Enrollment.objects.create(student=user, course=self.course)
            self.client.force_authenticate(user)
            self.assertEqual(self.client.post(self.url, {'rating': 4}, format='json').status_code, 403)
            self.assertEqual(self.client.patch(self.me, {'rating': 4}, format='json').status_code, 403)
            self.assertEqual(self.client.delete(self.me).status_code, 403)
            self.assertEqual(self.client.post(self.url, {'rating': 4, 'student_id': self.student.pk}, format='json').status_code, 400)
        self.student.is_active = False
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.post(self.url, {'rating': 4}, format='json').status_code, 403)

    def test_ownership_and_url_fields_rejected(self):
        self.client.post(self.url, {'rating': 3}, format='json')
        for field in ['student', 'student_id', 'user', 'user_id', 'course', 'course_id', 'instructor', 'instructor_id']:
            with self.subTest(field=field):
                data = {'rating': 5, field: self.other.pk}
                self.assertEqual(self.client.post(self.url, data, format='json').status_code, 400)
                self.assertEqual(self.client.patch(self.me, data, format='json').status_code, 400)
                self.assertEqual(self.client.delete(self.me, data, format='json').status_code, 400)
        self.assertEqual(CourseReview.objects.get().rating, 3)

    def test_duplicate_api_and_database_constraints(self):
        self.assertEqual(self.client.post(self.url, {'rating': 2}, format='json').status_code, 201)
        self.assertEqual(self.client.post(self.url, {'rating': 4}, format='json').status_code, 400)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CourseReview.objects.create(student=self.student, course=self.course, rating=4)
        for rating in [0, 6]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                CourseReview.objects.create(student=self.other, course=self.course, rating=rating)

    def test_own_update_delete_and_other_student_isolation(self):
        self.client.post(self.url, {'rating': 2, 'review': 'Original'}, format='json')
        self.client.force_authenticate(self.other)
        Enrollment.objects.create(student=self.other, course=self.course)
        self.assertEqual(self.client.patch(self.me, {'rating': 5}, format='json').status_code, 404)
        self.assertEqual(self.client.delete(self.me).status_code, 404)
        self.assertEqual(CourseReview.objects.get().rating, 2)
        self.client.post(self.url, {'rating': 1}, format='json')
        self.assertEqual(self.client.patch(self.me, {'rating': 4}, format='json').status_code, 200)
        self.assertEqual(self.client.delete(self.me).status_code, 204)
        self.assertEqual(CourseReview.objects.get().student_id, self.student.pk)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.patch(self.me, {'rating': 5, 'review': 'Changed'}, format='json').status_code, 200)
        self.assertEqual(CourseReview.objects.get().review, 'Changed')
        self.assertEqual(self.client.delete(self.me).status_code, 204)

    def test_aggregates_change_after_update_and_delete(self):
        self.assertIsNone(self.stats()['average_rating'])
        self.assertEqual(self.stats()['review_count'], 0)
        self.client.post(self.url, {'rating': 1}, format='json')
        CourseReview.objects.create(student=self.other, course=self.course, rating=5)
        another = Course.objects.create(title='Second', course_type='skill', instructor=self.instructor, is_published=True)
        CourseReview.objects.create(student=self.other, course=another, rating=3)
        self.assertEqual(self.stats()['average_rating'], 3)
        self.assertEqual(self.stats()['review_count'], 2)
        instructor = with_instructor_review_stats().get(pk=self.instructor.pk)
        self.assertEqual(instructor.average_rating, 3)
        self.assertEqual(instructor.review_count, 3)
        self.client.patch(self.me, {'rating': 3}, format='json')
        self.assertEqual(self.stats()['average_rating'], 4)
        self.assertAlmostEqual(with_instructor_review_stats().get(pk=self.instructor.pk).average_rating, 11 / 3)
        self.client.delete(self.me)
        self.assertEqual(self.stats()['average_rating'], 5)
        self.assertEqual(self.stats()['review_count'], 1)
        self.assertEqual(with_instructor_review_stats().get(pk=self.instructor.pk).average_rating, 4)
        self.assertEqual(with_instructor_review_stats().get(pk=self.instructor.pk).review_count, 2)

    def test_review_list_safe_identity_and_no_n_plus_one(self):
        CourseReview.objects.create(student=self.student, course=self.course, rating=3)
        CourseReview.objects.create(student=self.other, course=self.course, rating=5)
        with self.assertNumQueries(2):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        for review in response.data:
            self.assertEqual(set(review), {'id', 'rating', 'review', 'student', 'created_at', 'updated_at'})
            self.assertEqual(set(review['student']), {'id', 'name'})
        with self.assertNumQueries(1):
            data = CourseSerializer(Course.objects.with_review_stats().select_related('instructor', 'subject', 'grade'), many=True).data
            self.assertEqual(data[0]['review_count'], 2)

    def test_visibility_and_authentication(self):
        self.client.force_authenticate(None)
        for method, url in [('get', self.url), ('post', self.url), ('patch', self.me), ('delete', self.me)]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 401)
        self.course.is_published = False
        self.course.save()
        self.client.force_authenticate(self.student)
        for method, url in [('get', self.url), ('post', self.url), ('patch', self.me), ('delete', self.me)]:
            self.assertEqual(getattr(self.client, method)(url, {'rating': 3}, format='json').status_code, 404)
        self.assertEqual(self.client.get(self.detail).status_code, 404)
        self.assertEqual(self.client.get(reverse('api-course-list-create')).data, [])
        for user in [self.instructor, self.admin]:
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url).status_code, 200)
            self.assertEqual(self.client.get(self.detail).status_code, 200)
            self.assertEqual(len(self.client.get(reverse('api-course-list-create')).data), 1)
        outsider = User.objects.create_user(email='outsider@example.com', role=self.instructor.role)
        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_cancelled_enrollment_can_delete_but_not_update(self):
        self.client.post(self.url, {'rating': 4}, format='json')
        self.enrollment.status = 'cancelled'
        self.enrollment.save()
        self.assertEqual(self.client.patch(self.me, {'rating': 5}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(self.me).status_code, 204)

    def test_deletion_conventions(self):
        CourseReview.objects.create(student=self.other, course=self.course, rating=3)
        self.other.delete()
        self.assertFalse(CourseReview.objects.exists())
        CourseReview.objects.create(student=self.student, course=self.course, rating=3)
        self.course.delete()
        self.assertFalse(CourseReview.objects.exists())

    def test_enrollment_and_progress_regression(self):
        lesson = Lesson.objects.create(course=self.course, title='Lesson', content_type='text')
        response = self.client.post(reverse('api-complete-lesson', kwargs={'lesson_id': lesson.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(LessonProgress.objects.get(student=self.student, lesson=lesson).is_completed)
        response = self.client.get(reverse('api-course-progress', kwargs={'course_id': self.course.pk}))
        self.assertEqual(response.status_code, 200)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, 'completed')

    def test_course_and_enrollment_regression(self):
        self.client.force_authenticate(self.instructor)
        response = self.client.post(reverse('api-course-list-create'), {'title': 'New course', 'course_type': 'skill'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.data['average_rating'])
        self.assertEqual(response.data['review_count'], 0)
        self.assertFalse(response.data['is_published'])
        new_course = Course.objects.get(pk=response.data['id'])
        new_course.is_published = True
        new_course.save()
        self.client.force_authenticate(self.student)
        enroll_url = reverse('api-enroll-course', kwargs={'course_id': new_course.pk})
        self.assertEqual(self.client.post(enroll_url).status_code, 201)
        self.assertEqual(self.client.post(enroll_url).status_code, 400)
        self.assertEqual(self.client.get(reverse('api-my-enrollments')).status_code, 200)
        with self.assertNumQueries(1):
            self.assertEqual(self.client.get(reverse('api-course-list-create')).status_code, 200)

    def test_reviews_do_not_change_rewards(self):
        from .models import PointTransaction, Reward, Redemption
        PointTransaction.objects.create(student=self.student, points=100, event_type='quiz_correct')
        reward = Reward.objects.create(name='Test reward', points_required=25, stock=2)
        self.client.post(self.url, {'rating': 4}, format='json')
        self.client.patch(self.me, {'rating': 5}, format='json')
        self.client.delete(self.me)
        self.assertEqual(PointTransaction.objects.filter(student=self.student).count(), 1)
        self.assertEqual(self.client.get(reverse('api-rewards')).status_code, 200)
        response = self.client.post(reverse('api-redeem-reward'), {'reward_id': reward.pk}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['remaining_points'], 75)
        self.assertEqual(Redemption.objects.filter(student=self.student).count(), 1)
        reward.refresh_from_db()
        self.assertEqual(reward.stock, 1)

    def test_jwt_authentication_rules(self):
        from rest_framework_simplejwt.tokens import RefreshToken
        self.client.force_authenticate(None)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.student).access_token}')
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.student.email_verified = False
        self.student.save()
        self.assertEqual(self.client.post(self.url, {'rating': 3}, format='json').status_code, 401)
        self.student.email_verified = True
        self.student.is_active = False
        self.student.save()
        self.assertEqual(self.client.get(self.url).status_code, 401)


class AuthenticationFlowTests(TestCase):
	def setUp(self):
		self.role = Role.objects.get(name='school_admin')
		self.user = User.objects.create_user(
			email='admin@example.com',
			password='A-strong-password-123',
			name='Admin User',
			role=self.role,
		)

	def test_login_page_is_custom(self):
		response = self.client.get(reverse('login'))
		self.assertContains(response, 'Welcome back')
		self.assertContains(response, 'Admin access')

	def test_incomplete_onboarding_cannot_login(self):
		response = self.client.post(reverse('login'), {
			'email': self.user.email,
			'password': 'A-strong-password-123',
		})
		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Complete onboarding before signing in.')
		self.assertNotIn('_auth_user_id', self.client.session)

	def test_completed_user_can_open_dashboard(self):
		self.user.onboarding_completed = True
		self.user.save(update_fields=['onboarding_completed'])
		response = self.client.post(reverse('login'), {
			'email': self.user.email,
			'password': 'A-strong-password-123',
		})
		self.assertRedirects(response, reverse('dashboard'))
		self.assertContains(self.client.get(reverse('dashboard')), 'Recent users')

	def test_role_permission_lookup(self):
		permission = Permission.objects.get(name='verify_instructor')
		self.role.role_permissions.get_or_create(permission=permission)
		self.assertTrue(self.user.has_role_permission('verify_instructor'))

	def test_superuser_is_stored_with_super_admin_role(self):
		superuser = User.objects.create_superuser(
			email='owner@example.com',
			password='A-strong-password-123',
			name='Platform Owner',
		)
		self.assertEqual(superuser.role.name, 'super_admin')
		self.assertTrue(superuser.onboarding_completed)


class GeographyManagementTests(TestCase):
	def setUp(self):
		self.super_admin = User.objects.create_superuser(
			email='owner@example.com',
			password='A-strong-password-123',
			name='Platform Owner',
		)
		self.client.force_login(self.super_admin)

	def test_super_admin_can_create_geography_records(self):
		response = self.client.post(reverse('manage_geography'), {'form_type': 'province', 'province-name': 'Bagmati'})
		self.assertRedirects(response, reverse('manage_geography'))
		province = Province.objects.get(name='Bagmati')

		response = self.client.post(reverse('manage_geography'), {
			'form_type': 'district',
			'district-name': 'Kathmandu',
			'district-province': province.pk,
		})
		self.assertRedirects(response, reverse('manage_geography'))
		district = District.objects.get(name='Kathmandu')

		self.client.post(reverse('manage_geography'), {
			'form_type': 'municipality',
			'municipality-name': 'Kirtipur',
			'municipality-district': district.pk,
		})
		self.client.post(reverse('manage_geography'), {
			'form_type': 'school',
			'school-name': 'SkillSikka Academy',
			'school-municipality': Municipality.objects.get(name='Kirtipur').pk,
			'school-sector': 'private',
			'school-logo_url': '',
		})
		self.client.post(reverse('manage_geography'), {'form_type': 'grade', 'grade-name': 'Grade 8'})

		self.assertTrue(Municipality.objects.filter(name='Kirtipur', district=district).exists())
		self.assertTrue(School.objects.filter(name='SkillSikka Academy', municipality__name='Kirtipur').exists())
		self.assertTrue(Grade.objects.filter(name='Grade 8').exists())

	def test_non_super_admin_cannot_create_geography_records(self):
		user = User.objects.create_user(
			email='staff@example.com',
			password='A-strong-password-123',
			name='Staff User',
			role=Role.objects.get(name='school_admin'),
		)
		self.client.force_login(user)
		response = self.client.post(reverse('manage_geography'), {'form_type': 'province', 'province-name': 'Blocked'})

		self.assertRedirects(response, reverse('dashboard'))
		self.assertFalse(Province.objects.filter(name='Blocked').exists())


class RegistrationApiTests(TestCase):
	def setUp(self):
		self.province = Province.objects.create(name='Registration Test Province')
		self.district = District.objects.create(name='Registration Test District', province=self.province)
		self.municipality = Municipality.objects.create(name='Registration Test Municipality', district=self.district)
		self.school = School.objects.create(name='SkillSikka Academy', municipality=self.municipality, sector='private')
		self.grade = Grade.objects.create(name='Registration Test Grade')

	def student_payload(self, **overrides):
		payload = {
			'email': 'student@example.com',
			'password': 'A-strong-password-123',
			'confirm_password': 'A-strong-password-123',
			'name': 'Student User',
			'gender': 'female',
			'dob': '01/01/2010',
			'phone_country_code': '+977',
			'phone_number': '9812345678',
			'location': 'Kirtipur',
			'province_id': self.province.pk,
			'district_id': self.district.pk,
			'municipality_id': self.municipality.pk,
			'grade_id': self.grade.pk,
		}
		payload.update(overrides)
		return payload

	def test_student_registration_creates_incomplete_profile_without_optional_school(self):
		response = self.client.post('/api/v1/register/student/', self.student_payload(), content_type='application/json')
		self.assertEqual(response.status_code, 201)
		user = User.objects.get(email='student@example.com')
		self.assertTrue(StudentProfile.objects.filter(user=user, school=None, grade=None).exists())
		self.assertEqual(user.role.name, 'student')
		self.assertEqual(user.verification_status, 'not_applicable')
		self.assertFalse(user.onboarding_completed)
		self.assertNotIn('tokens', response.json())
		self.assertTrue(response.json()['email_verification_required'])
		self.assertFalse(user.email_verified)

	def test_instructor_registration_requires_matching_address_and_supports_school(self):
		payload = {
			'email': 'instructor@example.com',
			'password': 'A-strong-password-123',
			'confirm_password': 'A-strong-password-123',
			'name': 'Instructor User',
			'gender': 'male',
			'dob': '01/01/1990',
			'phone_country_code': '+977',
			'phone_number': '9812345678',
			'location': 'Kirtipur',
			'province_id': self.province.pk,
			'district_id': self.district.pk,
			'municipality_id': self.municipality.pk,
			'school_id': self.school.pk,
			'qualification': 'Master of Computer Applications',
			'subject_expertise': 'Physics, Fullstack Web Dev',
			'experience_years': '5',
		}
		response = self.client.post('/api/v1/register/instructor/', payload, format='json')
		self.assertEqual(response.status_code, 201)
		profile = InstructorProfile.objects.get(user__email='instructor@example.com')
		self.assertEqual(profile.school, self.school)
		self.assertEqual(profile.province, self.province)


def png_upload(name):
	buffer = io.BytesIO()
	Image.new('RGB', (8, 8), 'teal').save(buffer, format='PNG')
	return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class CurrentUserProfileFieldsTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

	def setUp(self):
		self.province, _ = Province.objects.get_or_create(name='Test Province')
		self.district, _ = District.objects.get_or_create(name='Test District', province=self.province)
		self.municipality, _ = Municipality.objects.get_or_create(name='Test Municipality', district=self.district)
		self.school, _ = School.objects.get_or_create(name='Test School', municipality=self.municipality, sector='private')
		self.grade, _ = Grade.objects.get_or_create(name='Test Grade')

		other_district, _ = District.objects.get_or_create(name='Other District', province=self.province)
		other_municipality, _ = Municipality.objects.get_or_create(name='Other Municipality', district=other_district)
		self.other_school, _ = School.objects.get_or_create(name='Other School', municipality=other_municipality, sector='private')

		self.student = User.objects.create_user(
			email='me-student@example.com', password='A-strong-password-123',
			name='Student', role=Role.objects.get(name='student'),
		)
		StudentProfile.objects.create(user=self.student)

		self.instructor = User.objects.create_user(
			email='me-instructor@example.com', password='A-strong-password-123',
			name='Instructor', role=Role.objects.get(name='instructor'),
		)
		InstructorProfile.objects.create(user=self.instructor)

		self.client = APIClient()

	def complete_student(self, **overrides):
		payload = {
			'phone_country_code': '+977', 'phone_number': '9800000000', 'location': 'Kathmandu',
			'grade_id': self.grade.pk, 'province_id': self.province.pk,
			'district_id': self.district.pk, 'school_id': self.school.pk,
		}
		payload.update(overrides)
		return self.client.post('/api/v1/me/complete-profile/', payload, format='json')

	def complete_instructor(self, **overrides):
		payload = {
			'phone_country_code': '+977', 'phone_number': '9800000000', 'location': 'Kathmandu',
			'province_id': self.province.pk, 'district_id': self.district.pk,
			'municipality_id': self.municipality.pk,
			'qualification': 'MSc Physics', 'subject_expertise': 'Physics',
			'experience_years': 5,
		}
		payload.update(overrides)
		return self.client.post('/api/v1/instructor/complete-profile/', payload, format='json')

	def test_me_returns_every_completion_key_as_null_when_unset(self):
		self.client.force_authenticate(self.student)
		data = self.client.get('/api/v1/me/').json()

		for key in (
			'grade_id', 'province_id', 'district_id', 'municipality_id', 'school_id',
			'qualification', 'subject_expertise', 'experience_years',
			'profile_photo_url', 'student_id_card_url', 'cv_resume_url',
		):
			self.assertIn(key, data)
			self.assertIsNone(data[key], key)
		self.assertEqual(data['certificates_and_recommendations_urls'], [])

	def test_student_completion_fields_read_back_as_integers(self):
		self.client.force_authenticate(self.student)
		self.assertEqual(self.complete_student().status_code, 200)

		data = self.client.get('/api/v1/me/').json()
		self.assertEqual(data['grade_id'], self.grade.pk)
		self.assertEqual(data['province_id'], self.province.pk)
		self.assertEqual(data['district_id'], self.district.pk)
		self.assertEqual(data['school_id'], self.school.pk)
		# Derived from the school: the student form has no municipality step.
		self.assertEqual(data['municipality_id'], self.municipality.pk)

	def test_student_school_outside_district_is_rejected(self):
		self.client.force_authenticate(self.student)
		response = self.complete_student(school_id=self.other_school.pk)
		self.assertEqual(response.status_code, 400)
		self.assertIn('municipality_id', response.json())

	def test_instructor_completion_fields_read_back(self):
		self.client.force_authenticate(self.instructor)
		response = self.complete_instructor()
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['experience_years'], 5)

		data = self.client.get('/api/v1/me/').json()
		self.assertEqual(data['qualification'], 'MSc Physics')
		self.assertEqual(data['subject_expertise'], 'Physics')
		self.assertEqual(data['experience_years'], 5)
		self.assertEqual(data['municipality_id'], self.municipality.pk)
		self.assertIsNone(data['grade_id'])

	def test_fractional_experience_years_is_rejected(self):
		self.client.force_authenticate(self.instructor)
		response = self.complete_instructor(experience_years='2.5')
		self.assertEqual(response.status_code, 400)
		self.assertIn('experience_years', response.json())

	def test_student_uploads_photo_and_id_card_via_patch(self):
		self.client.force_authenticate(self.student)
		response = self.client.patch('/api/v1/me/', {
			'name': 'Renamed',
			'profile_photo': png_upload('me.png'),
			'student_id_card': SimpleUploadedFile('card.pdf', b'%PDF-1.4 card', content_type='application/pdf'),
		}, format='multipart')
		self.assertEqual(response.status_code, 200, response.content)

		data = response.json()
		self.assertEqual(data['name'], 'Renamed')
		self.assertTrue(data['profile_photo_url'].startswith('http://testserver/media/profile-photos/'))
		self.assertTrue(data['student_id_card_url'].startswith('http://testserver/api/v1/me/documents/'))

		document = self.client.get(data['student_id_card_url'])
		self.assertEqual(document.status_code, 200)
		self.assertEqual(b''.join(document.streaming_content), b'%PDF-1.4 card')

	def test_document_route_is_owner_only(self):
		document = VerificationDocument.objects.create(
			user=self.student, document_type='student_id_card', file_url='/media/x.pdf',
		)
		self.client.force_authenticate(self.instructor)
		self.assertEqual(self.client.get(f'/api/v1/me/documents/{document.pk}/').status_code, 404)

		self.client.force_authenticate(user=None)
		self.assertEqual(self.client.get(f'/api/v1/me/documents/{document.pk}/').status_code, 401)

	def test_instructor_uploads_cv_and_certificates(self):
		self.client.force_authenticate(self.instructor)
		response = self.client.patch('/api/v1/me/', {
			'cv_resume': SimpleUploadedFile('cv.pdf', b'%PDF-1.4 cv', content_type='application/pdf'),
			'certificates_and_recommendations': [
				SimpleUploadedFile('a.pdf', b'%PDF-1.4 a', content_type='application/pdf'),
				SimpleUploadedFile('b.pdf', b'%PDF-1.4 b', content_type='application/pdf'),
			],
		}, format='multipart')
		self.assertEqual(response.status_code, 200, response.content)
		data = response.json()
		self.assertIsNotNone(data['cv_resume_url'])
		self.assertEqual(len(data['certificates_and_recommendations_urls']), 2)

	def test_document_slots_are_role_specific(self):
		self.client.force_authenticate(self.instructor)
		response = self.client.patch('/api/v1/me/', {
			'student_id_card': SimpleUploadedFile('card.pdf', b'%PDF-1.4 x', content_type='application/pdf'),
		}, format='multipart')
		self.assertEqual(response.status_code, 400)
		self.assertIn('student_id_card', response.json())

	def upload_cv_as_instructor(self):
		self.client.force_authenticate(self.instructor)
		response = self.client.patch('/api/v1/me/', {
			'profile_photo': png_upload('me.png'),
			'cv_resume': SimpleUploadedFile('cv.pdf', b'%PDF-1.4 cv', content_type='application/pdf'),
		}, format='multipart')
		self.assertEqual(response.status_code, 200, response.content)
		self.client.force_authenticate(user=None)
		return VerificationDocument.objects.get(user=self.instructor, document_type='cv_resume')

	def make_super_admin(self):
		role, _ = Role.objects.get_or_create(name='super_admin')
		return User.objects.create_user(
			email='me-admin@example.com', password='A-strong-password-123',
			name='Admin', role=role,
		)

	def test_super_admin_api_sees_photo_and_documents(self):
		document = self.upload_cv_as_instructor()
		self.client.force_authenticate(self.make_super_admin())

		data = self.client.get(f'/api/v1/admin/users/{self.instructor.pk}/').json()
		self.assertTrue(data['profile_photo_url'].startswith('http://testserver/media/profile-photos/'))
		self.assertEqual(len(data['documents']), 1)
		self.assertEqual(data['documents'][0]['document_type'], 'cv_resume')

		response = self.client.get(data['documents'][0]['url'])
		self.assertEqual(response.status_code, 200)
		self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 cv')

		listed = self.client.get('/api/v1/admin/users/', {'role': 'instructor'}).json()['results']
		self.assertIsNotNone(next(u for u in listed if u['id'] == self.instructor.pk)['profile_photo_url'])

		# The document must belong to the user in the URL.
		self.assertEqual(
			self.client.get(f'/api/v1/admin/users/{self.student.pk}/documents/{document.pk}/').status_code,
			404,
		)

	def test_admin_document_api_is_super_admin_only(self):
		document = self.upload_cv_as_instructor()
		self.client.force_authenticate(self.student)
		response = self.client.get(f'/api/v1/admin/users/{self.instructor.pk}/documents/{document.pk}/')
		self.assertEqual(response.status_code, 403)

	def test_admin_web_pages_show_photo_and_documents(self):
		document = self.upload_cv_as_instructor()
		self.instructor.refresh_from_db()
		web = self.client_class()

		web.force_login(self.student)
		self.assertEqual(web.get(reverse('view_document', args=[document.pk])).status_code, 302)

		web.force_login(self.make_super_admin())
		response = web.get(reverse('view_document', args=[document.pk]))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 cv')

		page = web.get(reverse('edit_user', args=[self.instructor.pk]))
		self.assertContains(page, reverse('view_document', args=[document.pk]))
		self.assertContains(page, self.instructor.profile_photo_url)

	def test_oversized_profile_photo_is_rejected(self):
		self.client.force_authenticate(self.student)
		big = SimpleUploadedFile('big.png', b'0' * (5 * 1024 * 1024 + 1), content_type='image/png')
		response = self.client.patch('/api/v1/me/', {'profile_photo': big}, format='multipart')
		self.assertEqual(response.status_code, 400)
		self.assertIn('profile_photo', response.json())


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetOTPTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user(email='reset-student@example.com', name='Student',
            password='Original-strong-password-123!', role=Role.objects.get(name='student'))
        self.request_url = '/api/v1/forgot-password/'
        self.verify_url = self.request_url+'verify-otp/'
        self.reset_url = self.request_url+'reset/'

    def issue(self, number=7):
        with patch('core.serializers.secrets.randbelow', return_value=number) as random:
            response = self.client.post(self.request_url, {'email':self.user.email}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        random.assert_called_once_with(10000)
        otp = re.search(r'OTP is ([0-9]{4})\.', mail.outbox[-1].body).group(1)
        self.assertNotIn(otp, str(response.data))
        return otp

    def verify(self, otp, email=None):
        return self.client.post(self.verify_url, {'email':email or self.user.email,'otp':otp}, format='json')

    def test_generation_exact_four_numeric_digits_leading_zeros_hash_and_expiry(self):
        for number, expected in ((0,'0000'),(7,'0007'),(421,'0421'),(5832,'5832'),(9999,'9999')):
            with self.subTest(number=number):
                before = timezone.now()
                otp = self.issue(number)
                self.assertEqual(otp, expected)
                record = PasswordResetOTP.objects.filter(user=self.user).latest('pk')
                self.assertNotEqual(record.otp_hash, otp)
                self.assertTrue(check_password(otp, record.otp_hash))
                self.assertGreaterEqual(record.expires_at, before+timedelta(seconds=OTP_EXPIRY_SECONDS))
                self.assertLessEqual(record.expires_at, timezone.now()+timedelta(seconds=OTP_EXPIRY_SECONDS))

    def test_valid_leading_zero_otp_verifies_once_and_full_reset_login_works(self):
        otp = self.issue()
        response = self.verify(otp)
        self.assertEqual(response.status_code, 200, response.data)
        token = response.data['reset_token']
        self.assertTrue(PasswordResetOTP.objects.get(user=self.user).is_used)
        self.assertEqual(self.verify(otp).status_code, 400)
        password = 'New-strong-password-456!'
        response = self.client.post(self.reset_url, {'reset_token':token,'new_password':password,
                                   'confirm_password':password}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        response = self.client.post('/api/v1/login/', {'email':self.user.email,'password':password}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('tokens', response.data)
        self.assertEqual(self.client.post('/api/v1/login/', {'email':self.user.email,
            'password':'Original-strong-password-123!'}, format='json').status_code, 400)

    def test_wrong_otp_fails_without_consuming_valid_code(self):
        otp = self.issue()
        self.assertEqual(self.verify('9999').status_code, 400)
        self.assertFalse(PasswordResetOTP.objects.get(user=self.user).is_used)
        self.assertEqual(self.verify(otp).status_code, 200)

    def test_malformed_otp_formats_rejected_without_consuming_code(self):
        otp = self.issue()
        for value in ('007','00007','000007','abcd','0a07',' 0007','0007 ','0007\n',
                      '\u0660\u0660\u0660\u0667','-007','',None,1234,1234.0,True,[],{}):
            with self.subTest(value=value):
                response = self.verify(value)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn('otp', response.data)
                self.assertFalse(PasswordResetOTP.objects.get(user=self.user).is_used)
        self.assertEqual(self.verify(otp).status_code, 200)

    def test_expired_otp_is_rejected_and_marked_used(self):
        otp = self.issue()
        PasswordResetOTP.objects.filter(user=self.user).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.verify(otp).status_code, 400)
        self.assertTrue(PasswordResetOTP.objects.get(user=self.user).is_used)

    def test_new_request_invalidates_old_otp_without_new_cooldown(self):
        old = self.issue(7)
        new = self.issue(421)
        self.assertEqual(PasswordResetOTP.objects.filter(user=self.user,is_used=False).count(), 1)
        self.assertEqual(self.verify(old).status_code, 400)
        self.assertEqual(self.verify(new).status_code, 200)

    def test_unknown_email_response_matches_known_email_and_sends_no_email(self):
        self.issue()
        known = self.client.post(self.request_url, {'email':self.user.email}, format='json')
        count = len(mail.outbox)
        unknown = self.client.post(self.request_url, {'email':'unknown@example.com'}, format='json')
        self.assertEqual(unknown.status_code, known.status_code)
        self.assertEqual(unknown.data, known.data)
        self.assertEqual(len(mail.outbox), count)
        self.assertEqual(self.verify('0007',email='unknown@example.com').status_code, 400)

    def test_reset_password_validation_and_signed_token_expiry_unchanged(self):
        token = self.verify(self.issue()).data['reset_token']
        for data in ({'new_password':'123','confirm_password':'123'},
                     {'new_password':'Long-password-123','confirm_password':'Different-password-123'}):
            self.assertEqual(self.client.post(self.reset_url, dict(reset_token=token, **data), format='json').status_code, 400)
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp()+601):
            response = self.client.post(self.reset_url, {'reset_token':token,'new_password':'Long-password-123',
                'confirm_password':'Long-password-123'}, format='json')
        self.assertEqual(response.status_code, 400)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetOTPLiveTests(LiveServerTestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email='live-reset@example.com', name='Student',
            password='Original-password-123!', role=Role.objects.get_or_create(name='student')[0])

    def request(self, path, payload):
        req = urllib.request.Request(self.live_server_url+'/api/v1/'+path,
            data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.load(response)

    def test_real_http_four_digit_request_verify_reset_login(self):
        with patch('core.serializers.secrets.randbelow', return_value=7):
            status, body = self.request('forgot-password/', {'email':self.user.email})
        self.assertEqual(status, 200)
        otp = re.search(r'OTP is ([0-9]{4})\.', mail.outbox[-1].body).group(1)
        self.assertEqual(otp, '0007')
        self.assertNotIn(otp, str(body))
        status, body = self.request('forgot-password/verify-otp/', {'email':self.user.email,'otp':otp})
        self.assertEqual(status, 200)
        status, body = self.request('forgot-password/reset/', {'reset_token':body['reset_token'],
            'new_password':'Changed-password-456!','confirm_password':'Changed-password-456!'})
        self.assertEqual(status, 200)
        status, body = self.request('login/', {'email':self.user.email,'password':'Changed-password-456!'})
        self.assertEqual(status, 200)
        self.assertIn('tokens', body)


class ShortBookmarkTests(TestCase):
    def setUp(self):
        cache.clear()
        self.student = User.objects.create_user(email='bookmark-student@example.com', name='Student', role=Role.objects.get(name='student'))
        self.other = User.objects.create_user(email='bookmark-other@example.com', name='Other', role=Role.objects.get(name='student'))
        self.instructor = User.objects.create_user(email='bookmark-instructor@example.com', name='Instructor',
            role=Role.objects.get(name='instructor'), verification_status='verified')
        self.short = Short.objects.create(title='Published short', instructor=self.instructor, video_url='https://example.com/video', is_published=True)
        self.client = APIClient()
        self.client.force_authenticate(self.student)
        self.save_url = f'/api/v1/student/shorts/{self.short.pk}/save/'
        self.detail_url = f'/api/v1/shorts/{self.short.pk}/'
        self.list_url = '/api/v1/shorts/'
        self.saved_url = '/api/v1/student/shorts/saved/'

    def test_save_persists_and_repeated_post_is_idempotent(self):
        response = self.client.post(self.save_url)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['is_saved'])
        self.assertTrue(ShortBookmark.objects.filter(student=self.student, short=self.short).exists())
        first = ShortBookmark.objects.get()
        response = self.client.post(self.save_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['is_saved'])
        self.assertEqual(ShortBookmark.objects.count(), 1)
        self.assertEqual(ShortBookmark.objects.get().created_at, first.created_at)

    def test_unsave_and_repeated_delete_are_idempotent(self):
        self.client.post(self.save_url)
        for _ in range(2):
            response = self.client.delete(self.save_url)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.data['is_saved'])
            self.assertFalse(ShortBookmark.objects.exists())

    def test_student_specific_state_and_cross_user_deletion(self):
        self.client.post(self.save_url)
        self.client.force_authenticate(self.other)
        self.assertFalse(self.client.get(self.detail_url).data['is_saved'])
        self.assertEqual(self.client.get(self.saved_url).data, [])
        self.assertEqual(self.client.delete(self.save_url).status_code, 200)
        self.assertTrue(ShortBookmark.objects.filter(student=self.student).exists())
        self.client.post(self.save_url)
        self.assertEqual(ShortBookmark.objects.count(), 2)
        self.client.delete(self.save_url)
        self.assertTrue(ShortBookmark.objects.filter(student=self.student).exists())
        self.assertFalse(ShortBookmark.objects.filter(student=self.other).exists())

    def test_is_saved_in_list_detail_and_saved_list_preserves_fields(self):
        expected = {'id','title','instructor_id','instructor_name','video_url','thumbnail_url','is_published',
                    'view_count','like_count','comment_count','is_liked','is_saved','created_at','updated_at'}
        self.assertFalse(self.client.get(self.detail_url).data['is_saved'])
        self.assertFalse(self.client.get(self.list_url).data[0]['is_saved'])
        self.client.post(self.save_url)
        for body in (self.client.get(self.detail_url).data, self.client.get(self.list_url).data[0],
                     self.client.get(self.saved_url).data[0]):
            self.assertTrue(body['is_saved'])
            self.assertEqual(set(body), expected)
            self.assertEqual(body['id'], self.short.pk)

    def test_saved_order_by_bookmark_timestamp_then_id(self):
        now = timezone.now()
        first = ShortBookmark.objects.create(student=self.student, short=self.short)
        shorts = [Short.objects.create(title=str(i), instructor=self.instructor, video_url='https://example.com/video',
                  is_published=True) for i in range(2)]
        second = ShortBookmark.objects.create(student=self.student, short=shorts[0])
        third = ShortBookmark.objects.create(student=self.student, short=shorts[1])
        ShortBookmark.objects.filter(pk=first.pk).update(created_at=now-timedelta(days=1))
        ShortBookmark.objects.filter(pk__in=[second.pk, third.pk]).update(created_at=now)
        self.assertEqual([r['id'] for r in self.client.get(self.saved_url).data], [third.short_id,second.short_id,first.short_id])

    def test_unpublished_cannot_be_saved_but_existing_bookmark_can_be_removed(self):
        self.client.post(self.save_url)
        self.short.is_published = False
        self.short.save(update_fields=['is_published'])
        self.assertTrue(ShortBookmark.objects.exists())
        self.assertEqual(self.client.get(self.saved_url).data, [])
        self.assertEqual(self.client.post(self.save_url).status_code, 404)
        self.assertEqual(self.client.delete(self.save_url).status_code, 200)
        self.assertFalse(ShortBookmark.objects.exists())
        self.assertEqual(self.client.post(self.save_url).status_code, 404)

    def test_republished_saved_short_reappears_without_new_bookmark(self):
        self.client.post(self.save_url)
        original = ShortBookmark.objects.get().pk
        self.short.is_published = False
        self.short.save()
        self.assertEqual(self.client.get(self.saved_url).data, [])
        self.short.is_published = True
        self.short.save()
        self.assertEqual(self.client.get(self.saved_url).data[0]['id'], self.short.pk)
        self.assertEqual(ShortBookmark.objects.get().pk, original)

    def test_nonexistent_short_returns_404(self):
        missing = '/api/v1/student/shorts/999999/save/'
        self.assertEqual(self.client.post(missing).status_code, 404)
        self.assertEqual(self.client.delete(missing).status_code, 404)

    def test_anonymous_and_other_roles_denied(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post(self.save_url).status_code, 401)
        self.assertEqual(self.client.delete(self.save_url).status_code, 401)
        self.assertEqual(self.client.get(self.saved_url).status_code, 401)
        for role in ('instructor','super_admin','local_authority','ministry'):
            user = User.objects.create_user(email=role+'-bookmark-denied@example.com', name='Denied', role=Role.objects.get(name=role))
            self.client.force_authenticate(user)
            with self.subTest(role=role):
                self.assertEqual(self.client.post(self.save_url).status_code, 403)
                self.assertEqual(self.client.delete(self.save_url).status_code, 403)
                self.assertEqual(self.client.get(self.saved_url).status_code, 403)

    def test_request_body_cannot_choose_owner(self):
        for key in ('student','student_id','user','user_id'):
            with self.subTest(key=key):
                self.assertEqual(self.client.post(self.save_url, {key:self.other.pk}, format='json').status_code, 400)
                self.assertFalse(ShortBookmark.objects.exists())
        self.client.post(self.save_url)
        response = self.client.delete(self.save_url, {'student_id':self.other.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(ShortBookmark.objects.exists())

    def test_duplicate_database_constraint_and_cascade_deletion(self):
        ShortBookmark.objects.create(student=self.student, short=self.short)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ShortBookmark.objects.create(student=self.student, short=self.short)
        self.short.delete()
        self.assertFalse(ShortBookmark.objects.exists())

    def test_bookmark_state_has_no_per_short_queries(self):
        def bookmark_queries(path):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
            sql = [q['sql'] for q in queries if 'short_bookmarks' in q['sql']]
            self.assertEqual(len(sql), 1, sql)
            self.assertIn('EXISTS', sql[0].upper())
        self.client.post(self.save_url)
        bookmark_queries(self.list_url)
        for i in range(6):
            short = Short.objects.create(title=str(i), instructor=self.instructor, video_url='https://example.com/v', is_published=True)
            ShortBookmark.objects.create(student=self.student, short=short)
        bookmark_queries(self.list_url)
        bookmark_queries(self.detail_url)
        bookmark_queries(self.saved_url)

    def test_serializer_without_authenticated_student_context_returns_false(self):
        self.short._is_saved = True
        self.assertFalse(ShortSerializer(self.short).data['is_saved'])
        from django.contrib.auth.models import AnonymousUser
        for user in (AnonymousUser(), self.instructor):
            serializer = ShortSerializer(self.short, context={'request':SimpleNamespace(user=user)})
            self.assertFalse(serializer.data['is_saved'])

    def test_existing_views_likes_comments_and_is_liked_unchanged(self):
        self.client.post(self.save_url)
        prefix = f'/api/v1/student/shorts/{self.short.pk}/'
        self.assertEqual(self.client.post(prefix+'view/').status_code, 201)
        self.assertEqual(self.client.post(prefix+'view/').status_code, 200)
        response = self.client.post(prefix+'like/')
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['is_liked'])
        self.assertEqual(self.client.post(prefix+'comments/', {'text':'Helpful lesson'}, format='json').status_code, 201)
        detail = self.client.get(self.detail_url).data
        self.assertTrue(detail['is_saved'])
        self.assertTrue(detail['is_liked'])
        self.assertEqual((detail['view_count'],detail['like_count'],detail['comment_count']), (1,1,1))
        self.assertEqual(self.client.get(prefix+'comments/').data[0]['text'], 'Helpful lesson')
        self.assertFalse(self.client.post(prefix+'like/').data['is_liked'])
        self.assertTrue(self.client.get(self.detail_url).data['is_saved'])
        self.assertEqual(ShortView.objects.count(), 1)
        self.assertEqual(ShortLike.objects.count(), 0)
        self.assertEqual(ShortComment.objects.count(), 1)

    def test_short_crud_visibility_ownership_and_is_saved_read_only(self):
        self.client.force_authenticate(self.instructor)
        response = self.client.post(self.list_url, {'title':'Draft', 'video_url':'https://example.com/new', 'is_saved':True}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['is_saved'])
        draft_url = f"/api/v1/shorts/{response.data['id']}/"
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get(draft_url).status_code, 404)
        self.assertEqual(len(self.client.get(self.list_url).data), 1)
        self.assertEqual(self.client.patch(self.detail_url, {'title':'Not owner'}, format='json').status_code, 403)
        self.client.force_authenticate(self.instructor)
        self.assertEqual(len(self.client.get(self.list_url).data), 2)
        self.assertEqual(self.client.patch(draft_url, {'is_published':True}, format='json').status_code, 200)
        other_instructor = User.objects.create_user(email='other-owner@example.com', name='Other', role=Role.objects.get(name='instructor'))
        self.client.force_authenticate(other_instructor)
        self.assertEqual(self.client.delete(draft_url).status_code, 403)
        admin = User.objects.create_user(email='short-admin@example.com', name='Admin', role=Role.objects.get(name='super_admin'))
        self.client.force_authenticate(admin)
        self.assertEqual(self.client.get(draft_url).status_code, 200)
        self.assertFalse(self.client.get(draft_url).data['is_saved'])
        self.assertEqual(self.client.delete(draft_url).status_code, 204)


class ShortBookmarkLiveTests(LiveServerTestCase):
    def setUp(self):
        cache.clear()
        role = Role.objects.get_or_create(name='student')[0]
        self.password = 'Live-bookmarks-Strong-123!'
        self.students = [User.objects.create_user(email=f'live-bookmark-{i}@example.com', name='Student', role=role,
                         password=self.password) for i in range(2)]
        instructor = User.objects.create_user(email='live-bookmark-instructor@example.com', name='Instructor',
            role=Role.objects.get_or_create(name='instructor')[0])
        self.short = Short.objects.create(title='Live short', instructor=instructor, video_url='https://example.com/video', is_published=True)

    def request(self, path, token=None, payload=None, method=None):
        headers = {'Content-Type':'application/json'}
        if token:
            headers['Authorization'] = 'Bearer '+token
        req = urllib.request.Request(self.live_server_url+'/api/v1/'+path,
            data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_real_http_login_save_state_list_idempotency_and_owner_isolation(self):
        tokens = []
        for student in self.students:
            status, body = self.request('login/', payload={'email':student.email,'password':self.password})
            self.assertEqual(status, 200, body)
            tokens.append(body['tokens']['access'])
        first, second = tokens
        detail = f'shorts/{self.short.pk}/'
        save = f'student/shorts/{self.short.pk}/save/'
        saved = 'student/shorts/saved/'
        self.assertFalse(self.request(detail, first)[1]['is_saved'])
        self.assertEqual(self.request(save, first, method='POST'), (201, {'short_id':self.short.pk,'is_saved':True}))
        self.assertTrue(self.request(detail, first)[1]['is_saved'])
        self.assertTrue(self.request('shorts/', first)[1][0]['is_saved'])
        self.assertEqual(self.request(saved, first)[1][0]['id'], self.short.pk)
        self.assertEqual(self.request(save, first, method='POST')[0], 200)
        self.assertEqual(ShortBookmark.objects.count(), 1)
        self.assertFalse(self.request(detail, second)[1]['is_saved'])
        self.assertEqual(self.request(save, second, method='DELETE')[0], 200)
        self.assertTrue(self.request(detail, first)[1]['is_saved'])
        for _ in range(2):
            self.assertEqual(self.request(save, first, method='DELETE'), (200, {'short_id':self.short.pk,'is_saved':False}))
        self.assertFalse(self.request(detail, first)[1]['is_saved'])
        self.assertEqual(self.request(saved, first), (200, []))
