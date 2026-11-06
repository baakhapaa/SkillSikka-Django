import re
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.contrib.auth.hashers import check_password
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .models import InstructorSignupOTP, PasswordResetOTP, Role, User
from .signup_otp import OTP_MAX_ISSUES_PER_DAY


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PasswordResetOTPTests(TestCase):
	def setUp(self):
		cache.clear()
		self.addCleanup(cache.clear)
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

	def test_public_reset_with_missing_invalid_and_expired_bearer_headers(self):
		expired = AccessToken()
		expired.set_exp(lifetime=timedelta(seconds=-60))
		for index, header in enumerate((None, 'Bearer invalid-token', 'Bearer ' + str(expired))):
			with self.subTest(header_type=index):
				cache.clear()
				self.client.credentials(**({'HTTP_AUTHORIZATION': header} if header else {}))
				otp = self.request_otp()
				self.assertRegex(otp, r'\A[0-9]{4}\Z')
				record = PasswordResetOTP.objects.get(user=self.user, is_used=False)
				self.assertTrue(check_password(otp, record.otp_hash))
				self.assertNotEqual(otp, record.otp_hash)
				self.assertEqual(mail.outbox[-1].to, [self.user.email])
				verified = self.verify(otp)
				self.assertEqual(verified.status_code, 200)
				self.assertNotIn('tokens', verified.data)
				password = f'New-strong-password-{index}-reset!'
				self.assertEqual(self.reset(verified.data['reset_token'], password).status_code, 200)
				self.client.credentials()
				self.assertEqual(self.client.post('/api/v1/login/', {
					'email': self.user.email, 'password': password,
				}, format='json').status_code, 200)

	def test_failed_initial_send_leaves_no_otp_and_returns_safe_error(self):
		for failure in ({'side_effect': RuntimeError('Private transport details')}, {'return_value': 0}):
			with self.subTest(failure=list(failure)):
				with patch('core.serializers.send_mail', **failure):
					response = self.client.post('/api/v1/forgot-password/', {'email': self.user.email}, format='json')
				self.assertEqual(response.status_code, 503)
				self.assertEqual(str(response.data['detail']),
					'Unable to send a password reset email right now. Please try again later.')
				self.assertFalse(PasswordResetOTP.objects.filter(user=self.user).exists())

	def test_failed_resend_preserves_previous_code_and_all_its_state(self):
		for failure in ({'side_effect': RuntimeError('Private transport details')}, {'return_value': 0}):
			with self.subTest(failure=list(failure)):
				cache.clear()
				otp = self.request_otp()
				record = PasswordResetOTP.objects.get(user=self.user, is_used=False)
				record.failed_attempts = 1
				record.save(update_fields=['failed_attempts'])
				before = PasswordResetOTP.objects.filter(user=self.user).count()
				state = (record.otp_hash, record.expires_at, record.created_at, record.failed_attempts)
				with patch('core.serializers.send_mail', **failure):
					response = self.client.post('/api/v1/forgot-password/', {'email': self.user.email}, format='json')
				self.assertEqual(response.status_code, 503)
				record.refresh_from_db()
				self.assertFalse(record.is_used)
				self.assertEqual((record.otp_hash, record.expires_at, record.created_at, record.failed_attempts), state)
				self.assertEqual(PasswordResetOTP.objects.filter(user=self.user).count(), before)
				self.assertEqual(self.verify(otp).status_code, 200)

	def test_successful_resend_replaces_old_code_and_new_code_verifies(self):
		with patch('core.serializers.secrets.randbelow', return_value=7):
			old = self.request_otp()
		with patch('core.serializers.secrets.randbelow', return_value=421):
			new = self.request_otp()
		self.assertEqual(PasswordResetOTP.objects.filter(user=self.user, is_used=False).count(), 1)
		self.assertEqual(self.verify(old).status_code, 400)
		self.assertEqual(self.verify(new).status_code, 200)

	def test_unknown_email_stays_generic_even_when_mail_service_is_unavailable(self):
		self.request_otp()
		known = self.client.post('/api/v1/forgot-password/', {'email': self.user.email}, format='json')
		count = len(mail.outbox)
		with patch('core.serializers.send_mail', side_effect=RuntimeError('Unavailable')) as send:
			unknown = self.client.post('/api/v1/forgot-password/', {'email': 'unknown@example.com'}, format='json')
			send.assert_not_called()
		self.assertEqual(unknown.status_code, 200)
		self.assertEqual(unknown.data, known.data)
		self.assertEqual(len(mail.outbox), count)

	def test_public_reset_keeps_validation_and_anonymous_throttling(self):
		self.client.credentials(HTTP_AUTHORIZATION='Bearer invalid-token')
		for url in ('/api/v1/forgot-password/', '/api/v1/forgot-password/verify-otp/', '/api/v1/forgot-password/reset/'):
			cache.clear()
			for _ in range(20):
				self.assertEqual(self.client.post(url, {}, format='json').status_code, 400)
			self.assertEqual(self.client.post(url, {}, format='json').status_code, 429)


class InstructorPasswordResetOTPTests(PasswordResetOTPTests):
	def setUp(self):
		super().setUp()
		self.user.role = Role.objects.get(name='instructor')
		self.user.save(update_fields=['role'])


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
