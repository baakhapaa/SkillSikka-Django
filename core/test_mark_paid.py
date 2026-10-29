"""`mark_paid` — the sandbox escape hatch.

eSewa's test environment cannot be logged into when its reCAPTCHA quota is
exhausted, so the half of the flow after payment would otherwise be untestable.
These tests pin that the command settles through the *real* code path and that
it cannot run anywhere real money moves.
"""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .models import Course, Enrollment, Notification, Payment, Role, User


class MarkPaidTests(TestCase):
	def setUp(self):
		instructor = User.objects.create_user(
			email='mark-instructor@example.com', password='A-strong-password-123',
			name='Teacher', role=Role.objects.get(name='instructor'),
		)
		self.student = User.objects.create_user(
			email='mark-student@example.com', password='A-strong-password-123',
			name='Student', role=Role.objects.get(name='student'),
		)
		self.course = Course.objects.create(
			title='Paid Physics', instructor=instructor, course_type='academic',
			is_paid=True, price=Decimal('1500.00'), is_published=True,
		)
		self.enrollment = Enrollment.objects.create(
			student=self.student, course=self.course, status='pending_payment',
		)
		self.payment = Payment.objects.create(
			student=self.student, course=self.course, enrollment=self.enrollment,
			amount=Decimal('1500.00'), provider='esewa',
			transaction_reference='ref-mark-paid', status='initiated',
		)

	def run_command(self, *args):
		out = StringIO()
		call_command('mark_paid', *args, stdout=out)
		return out.getvalue()

	def test_it_settles_the_payment_and_opens_the_course(self):
		output = self.run_command(str(self.payment.pk))

		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, 'successful')
		self.assertEqual(self.payment.gateway_transaction_id, f'SANDBOX-{self.payment.pk}')
		self.assertIsNotNone(self.payment.verified_at)

		# The point of the command: the same enrolment activation the real
		# refresh performs, not a parallel one.
		self.enrollment.refresh_from_db()
		self.assertEqual(self.enrollment.status, 'active')
		self.assertEqual(self.enrollment.amount_paid, Decimal('1500.00'))
		self.assertEqual(self.enrollment.payment_reference, 'ref-mark-paid')

		self.assertEqual(
			Notification.objects.filter(notification_type='payment').count(), 1,
		)
		self.assertIn('successful', output)

	def test_it_refuses_to_run_against_live_payments(self):
		with override_settings(PAYMENT_MODE='live'):
			with self.assertRaises(CommandError) as caught:
				self.run_command(str(self.payment.pk))

		self.assertIn('PAYMENT_MODE=live', str(caught.exception))
		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, 'initiated')

	def test_it_does_not_settle_a_payment_twice(self):
		self.run_command(str(self.payment.pk))
		output = self.run_command(str(self.payment.pk))

		self.assertIn('already', output)
		self.assertEqual(
			Notification.objects.filter(notification_type='payment').count(), 1,
		)

	def test_a_missing_payment_is_an_error(self):
		with self.assertRaises(CommandError):
			self.run_command('999999')

	def test_it_can_record_a_cancellation(self):
		self.run_command(str(self.payment.pk), '--status', 'cancelled')

		self.payment.refresh_from_db()
		self.assertEqual(self.payment.status, 'cancelled')
		self.enrollment.refresh_from_db()
		self.assertEqual(self.enrollment.status, 'pending_payment')
