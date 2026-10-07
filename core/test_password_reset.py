import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import InstructorSignupOTP, PasswordResetOTP, Role, User
from .signup_otp import OTP_MAX_ISSUES_PER_DAY


class PasswordResetOTPTests(TestCase):
	def setUp(self):
		self.client = APIClient()
		self.user = User.objects.create_user(
			email='reset@example.com', password='Old-strong-password-1',
			name='Reset User', role=Role.objects.get(name='student'),
		)

	def request_otp(self):
		mail.outbox.clear()
		self.client.post('/api/v1/forgot-password/', {'email': self.user.email}, format='json')
		if not mail.outbox:
			return None
		return re.search(r'OTP is ([0-9]{4})\.', mail.outbox[-1].body).group(1)

	def verify(self, otp):
		return self.client.post('/api/v1/forgot-password/verify-otp/', {
			'email': self.user.email, 'otp': otp,
		}, format='json')

	def reset(self, token, password='New-strong-password-2'):
		return self.client.post('/api/v1/forgot-password/reset/', {
			'reset_token': token, 'new_password': password, 'confirm_password': password,
		}, format='json')

	def test_wrong_guesses_are_limited(self):
		otp = self.request_otp()
		wrong = '0000' if otp != '0000' else '0001'

		for _ in range(5):
			self.assertEqual(self.verify(wrong).status_code, 400)

		self.assertEqual(PasswordResetOTP.objects.get(user=self.user).failed_attempts, 5)
		# The real code no longer works once the limit is reached.
		self.assertEqual(self.verify(otp).status_code, 400)

	def test_reset_token_works_once_and_signs_out_sessions(self):
		refresh = RefreshToken.for_user(self.user)
		token = self.verify(self.request_otp()).json()['reset_token']

		self.assertEqual(self.reset(token).status_code, 200)
		self.assertEqual(self.reset(token, 'Another-strong-password-3').status_code, 400)

		self.user.refresh_from_db()
		self.assertTrue(self.user.check_password('New-strong-password-2'))

		response = self.client.post('/api/v1/token/refresh/', {'refresh': str(refresh)}, format='json')
		self.assertEqual(response.status_code, 401)

	def test_weak_new_password_is_rejected(self):
		token = self.verify(self.request_otp()).json()['reset_token']
		response = self.reset(token, '12345678')
		self.assertEqual(response.status_code, 400)
		self.assertIn('new_password', response.json())


class InstructorSignupResendCapTests(TestCase):
	def test_resend_stops_after_daily_cap(self):
		user = User.objects.create_user(
			email='cap@example.com', password='A-strong-password-123',
			name='Cap', role=Role.objects.get(name='instructor'), email_verified=False,
		)
		old = timezone.now() - timedelta(minutes=5)
		for _ in range(OTP_MAX_ISSUES_PER_DAY):
			InstructorSignupOTP.objects.create(user=user, otp_hash='x', expires_at=old)
		InstructorSignupOTP.objects.update(created_at=old)

		response = APIClient().post(
			'/api/v1/register/instructor/resend-otp/', {'email': user.email}, format='json',
		)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(mail.outbox), 0)
		self.assertEqual(InstructorSignupOTP.objects.filter(user=user).count(), OTP_MAX_ISSUES_PER_DAY)
