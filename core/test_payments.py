from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Course, Enrollment, Notification, Payment, Role, User
from .payments import esewa_signature


def gateway_response(body, status_code=200):
	response = MagicMock(status_code=status_code)
	response.json.return_value = body
	return response


@override_settings(
	KHALTI_SECRET_KEY='test-khalti-key',
	KHALTI_BASE_URL='https://dev.khalti.com/api/v2/',
	ESEWA_PRODUCT_CODE='EPAYTEST',
	ESEWA_SECRET_KEY='8gBm/:&EnhH.1/q',
	PAYMENT_APP_RETURN_URL='',
)
class PaymentFlowTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		instructor = User.objects.create_user(
			email='pay-instructor@example.com', password='A-strong-password-123',
			name='Teacher', role=Role.objects.get(name='instructor'),
		)
		self.student = User.objects.create_user(
			email='pay-student@example.com', password='A-strong-password-123',
			name='Student', role=Role.objects.get(name='student'),
		)
		self.course = Course.objects.create(
			title='Paid Physics', instructor=instructor, course_type='academic',
			is_paid=True, price=Decimal('1500.00'), is_published=True,
		)
		self.enrollment = Enrollment.objects.create(student=self.student, course=self.course, status='pending_payment')
		self.client.force_authenticate(self.student)

	def initiate(self, provider):
		return self.client.post(f'/api/v1/courses/{self.course.pk}/initiate-payment/', {'provider': provider}, format='json')

	# ---------- Khalti ----------

	@patch('core.payments.requests.post')
	def test_khalti_initiate_returns_payment_url(self, post):
		post.return_value = gateway_response({'pidx': 'PIDX123', 'payment_url': 'https://test-pay.khalti.com/?pidx=PIDX123'})

		response = self.initiate('khalti')
		self.assertEqual(response.status_code, 201, response.content)
		self.assertEqual(response.json()['payment_url'], 'https://test-pay.khalti.com/?pidx=PIDX123')

		payload = post.call_args.kwargs['json']
		self.assertEqual(payload['amount'], 150000)  # paisa
		self.assertIn('/api/v1/payments/khalti/return/', payload['return_url'])
		self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Key test-khalti-key')
		self.assertEqual(Payment.objects.get().gateway_token, 'PIDX123')

	@override_settings(KHALTI_SECRET_KEY='')
	def test_khalti_not_configured_is_503(self):
		response = self.initiate('khalti')
		self.assertEqual(response.status_code, 503)
		self.assertEqual(Payment.objects.get().status, 'failed')

	@patch('core.payments.requests.post')
	def test_khalti_return_completes_payment_once(self, post):
		post.return_value = gateway_response({'pidx': 'PIDX123', 'payment_url': 'https://x'})
		self.initiate('khalti')
		payment = Payment.objects.get()

		post.return_value = gateway_response({'pidx': 'PIDX123', 'status': 'Completed', 'total_amount': 150000, 'transaction_id': 'TXN9'})
		response = self.client.get(f'/api/v1/payments/khalti/return/{payment.transaction_reference}/?pidx=PIDX123&status=Completed')
		self.assertEqual(response.status_code, 302)
		self.assertIn('status=successful', response['Location'])

		payment.refresh_from_db()
		self.enrollment.refresh_from_db()
		self.assertEqual(payment.status, 'successful')
		self.assertEqual(payment.gateway_transaction_id, 'TXN9')
		self.assertEqual(self.enrollment.status, 'active')
		self.assertEqual(self.enrollment.amount_paid, Decimal('1500.00'))

		# Visiting the return URL again changes nothing and notifies once.
		self.client.get(f'/api/v1/payments/khalti/return/{payment.transaction_reference}/')
		self.assertEqual(Notification.objects.filter(recipient=self.student, notification_type='payment').count(), 1)

		page = self.client.get(response['Location'])
		self.assertContains(page, 'Payment successful')

	@patch('core.payments.requests.post')
	def test_khalti_amount_mismatch_fails(self, post):
		post.return_value = gateway_response({'pidx': 'PIDX123', 'payment_url': 'https://x'})
		self.initiate('khalti')
		payment = Payment.objects.get()

		post.return_value = gateway_response({'pidx': 'PIDX123', 'status': 'Completed', 'total_amount': 1000})
		self.client.get(f'/api/v1/payments/khalti/return/{payment.transaction_reference}/')
		payment.refresh_from_db()
		self.enrollment.refresh_from_db()
		self.assertEqual(payment.status, 'failed')
		self.assertEqual(self.enrollment.status, 'pending_payment')

	@patch('core.payments.requests.post')
	def test_khalti_pending_stays_initiated(self, post):
		post.return_value = gateway_response({'pidx': 'PIDX123', 'payment_url': 'https://x'})
		self.initiate('khalti')
		payment = Payment.objects.get()

		post.return_value = gateway_response({'pidx': 'PIDX123', 'status': 'Pending', 'total_amount': 150000})
		data = self.client.get(f'/api/v1/payments/{payment.pk}/').json()
		self.assertEqual(data['status'], 'initiated')

	# ---------- eSewa ----------

	def test_esewa_checkout_page_posts_signed_form(self):
		response = self.initiate('esewa')
		self.assertEqual(response.status_code, 201, response.content)
		payment = Payment.objects.get()
		self.assertIn(f'/api/v1/payments/esewa/checkout/{payment.transaction_reference}/', response.json()['payment_url'])

		self.client.force_authenticate(None)  # the WebView has no token
		page = self.client.get(response.json()['payment_url'])
		self.assertContains(page, 'action="https://rc-epay.esewa.com.np/api/epay/main/v2/form"')
		self.assertContains(page, 'name="total_amount" value="1500"')
		expected = esewa_signature(f'total_amount=1500,transaction_uuid={payment.transaction_reference},product_code=EPAYTEST')
		self.assertContains(page, f'name="signature" value="{expected}"')

	@patch('core.payments.requests.get')
	def test_esewa_return_complete(self, get):
		self.initiate('esewa')
		payment = Payment.objects.get()
		get.return_value = gateway_response({'status': 'COMPLETE', 'total_amount': 1500.0, 'ref_id': 'REF77'})

		response = self.client.get(f'/api/v1/payments/esewa/return/{payment.transaction_reference}/?data=whatever')
		self.assertIn('status=successful', response['Location'])
		self.assertEqual(get.call_args.kwargs['params']['transaction_uuid'], payment.transaction_reference)
		payment.refresh_from_db()
		self.assertEqual(payment.gateway_transaction_id, 'REF77')
		self.enrollment.refresh_from_db()
		self.assertEqual(self.enrollment.status, 'active')

	@patch('core.payments.requests.get')
	def test_esewa_cancelled(self, get):
		self.initiate('esewa')
		payment = Payment.objects.get()
		get.return_value = gateway_response({'status': 'CANCELED', 'total_amount': 1500.0})
		self.client.get(f'/api/v1/payments/esewa/return/{payment.transaction_reference}/')
		payment.refresh_from_db()
		self.assertEqual(payment.status, 'cancelled')

	# ---------- the old hole ----------

	@patch('core.payments.requests.get')
	def test_verify_ignores_client_claimed_success(self, get):
		self.initiate('esewa')
		payment = Payment.objects.get()
		get.return_value = gateway_response({'status': 'NOT_FOUND', 'total_amount': 1500.0})

		response = self.client.post('/api/v1/payments/verify/', {
			'transaction_reference': payment.transaction_reference, 'gateway_status': 'success',
		}, format='json')
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()['status'], 'failed')
		self.enrollment.refresh_from_db()
		self.assertEqual(self.enrollment.status, 'pending_payment')

	def test_cannot_verify_someone_elses_payment(self):
		self.initiate('esewa')
		payment = Payment.objects.get()
		other = User.objects.create_user(
			email='pay-other@example.com', password='A-strong-password-123',
			name='Other', role=Role.objects.get(name='student'),
		)
		self.client.force_authenticate(other)
		response = self.client.post('/api/v1/payments/verify/', {'transaction_reference': payment.transaction_reference}, format='json')
		self.assertEqual(response.status_code, 400)

	def test_paid_course_without_price_cannot_be_bought(self):
		Course.objects.filter(pk=self.course.pk).update(price=None)
		response = self.initiate('esewa')
		self.assertEqual(response.status_code, 400)
		self.assertFalse(Payment.objects.exists())


@override_settings(ESEWA_PRODUCT_CODE='EPAYTEST', ESEWA_SECRET_KEY='8gBm/:&EnhH.1/q')
class PaymentAdminTests(TestCase):
	def setUp(self):
		instructor = User.objects.create_user(
			email='padm-instructor@example.com', password='A-strong-password-123',
			name='Teacher', role=Role.objects.get(name='instructor'),
		)
		self.student = User.objects.create_user(
			email='padm-student@example.com', password='A-strong-password-123',
			name='Asha Student', role=Role.objects.get(name='student'),
		)
		self.course = Course.objects.create(
			title='Paid Chemistry', instructor=instructor, course_type='skill',
			is_paid=True, price=Decimal('500.00'),
		)
		enrollment = Enrollment.objects.create(student=self.student, course=self.course, status='pending_payment')
		self.done = Payment.objects.create(
			student=self.student, course=self.course, enrollment=enrollment, amount=Decimal('500.00'),
			provider='esewa', transaction_reference='ref-done', status='successful',
		)
		self.pending = Payment.objects.create(
			student=self.student, course=self.course, enrollment=enrollment, amount=Decimal('500.00'),
			provider='esewa', transaction_reference='ref-pending', status='initiated',
		)
		self.admin = User.objects.create_user(
			email='padm-admin@example.com', password='A-strong-password-123',
			name='Admin', role=Role.objects.get_or_create(name='super_admin')[0], onboarding_completed=True,
		)

	def test_payments_page_lists_and_filters(self):
		self.client.force_login(self.admin)
		page = self.client.get('/admin/payments')
		self.assertContains(page, 'Rs. 500.00')  # revenue counts successful only
		self.assertContains(page, 'Asha Student')
		self.assertContains(page, 'Re-check')

		filtered = self.client.get('/admin/payments?status=successful')
		self.assertContains(filtered, '1 payment')

	@patch('core.payments.requests.get')
	def test_recheck_button_asks_gateway(self, get):
		get.return_value = gateway_response({'status': 'COMPLETE', 'total_amount': 500.0, 'ref_id': 'R1'})
		self.client.force_login(self.admin)
		response = self.client.post(f'/admin/payments/{self.pending.pk}/recheck')
		self.assertEqual(response.status_code, 302)
		self.pending.refresh_from_db()
		self.assertEqual(self.pending.status, 'successful')

	def test_students_cannot_open_payments_page(self):
		self.client.force_login(self.student)
		self.assertEqual(self.client.get('/admin/payments').status_code, 302)
		self.assertEqual(self.client.post(f'/admin/payments/{self.pending.pk}/recheck').status_code, 302)
		self.pending.refresh_from_db()
		self.assertEqual(self.pending.status, 'initiated')

	@patch('core.payments.requests.get')
	def test_recheck_command_settles_abandoned_payments(self, get):
		from datetime import timedelta
		from io import StringIO

		from django.core.management import call_command
		from django.utils import timezone

		get.return_value = gateway_response({'status': 'NOT_FOUND', 'total_amount': 500.0})
		Payment.objects.filter(pk=self.pending.pk).update(created_at=timezone.now() - timedelta(minutes=30))

		out = StringIO()
		call_command('recheck_payments', stdout=out)
		self.pending.refresh_from_db()
		self.assertEqual(self.pending.status, 'failed')
		self.assertIn('Checked 1 payment(s): 1 failed', out.getvalue())

	def test_admin_course_form_requires_price_for_paid(self):
		from .forms import CourseForm

		form = CourseForm(data={
			'title': 'X', 'instructor': self.course.instructor_id, 'course_type': 'skill',
			'is_paid': 'on', 'price': '',
		})
		self.assertFalse(form.is_valid())
		self.assertIn('price', form.errors)
