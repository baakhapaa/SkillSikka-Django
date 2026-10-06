from datetime import timedelta
from contextlib import redirect_stdout
from io import StringIO
import json
import re
import urllib.error
import urllib.request
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.http import HttpResponse
from django.contrib.auth.hashers import check_password
from django.test import LiveServerTestCase, TestCase, TransactionTestCase, override_settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import District, InstructorSignupOTP, Municipality, PasswordResetOTP, Province, Role, User


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class InstructorSignupOTPTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        # Keep global throttles enabled in production; isolate test request counts.
        self.throttle = patch('rest_framework.views.APIView.check_throttles')
        self.throttle.start()
        self.addCleanup(self.throttle.stop)
        province = Province.objects.create(name='OTP province')
        district = District.objects.create(name='OTP district', province=province)
        municipality = Municipality.objects.create(name='OTP municipality', district=district)
        self.payload = {
            'email': 'instructor@example.com', 'name': 'Instructor',
            'password': 'A-strong-password-123', 'confirm_password': 'A-strong-password-123',
            'gender': 'male', 'dob': '1990-01-01', 'phone_country_code': '+977',
            'phone_number': '9812345678', 'location': 'Kirtipur',
            'province_id': province.pk, 'district_id': district.pk,
            'municipality_id': municipality.pk, 'qualification': 'Masters',
            'subject_expertise': 'Physics', 'experience_years': '5',
        }
        self.verify_url = '/api/v1/register/instructor/verify-otp/'
        self.resend_url = '/api/v1/register/instructor/resend-otp/'

    def register(self, url='/api/v1/register/instructor/'):
        response = self.client.post(url, self.payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.user = User.objects.get(email=self.payload['email'])
        self.otp = re.search(r'OTP is ([0-9]{4})\.', mail.outbox[-1].body).group(1)
        return response

    def verify(self, otp=None, email=None):
        return self.client.post(self.verify_url, {
            'email': email or self.payload['email'], 'otp': otp or self.otp,
        }, format='json')

    def allow_resend(self):
        InstructorSignupOTP.objects.filter(user=self.user).update(
            created_at=timezone.now() - timedelta(seconds=61),
        )

    def test_registration_is_unverified_pending_and_sends_hashed_four_digit_otp(self):
        response = self.register()
        self.assertFalse(self.user.email_verified)
        self.assertEqual(self.user.verification_status, 'pending')
        self.assertNotIn('tokens', response.data)
        self.assertTrue(response.data['email_verification_required'])
        record = self.user.instructor_signup_otps.get()
        self.assertNotEqual(record.otp_hash, self.otp)
        self.assertTrue(check_password(self.otp, record.otp_hash))
        self.assertAlmostEqual((record.expires_at - record.created_at).total_seconds(), 600, delta=2)
        self.assertEqual(mail.outbox[-1].to, [self.user.email])
        self.assertNotIn(self.otp, str(response.data))

    def test_unversioned_registration_also_requires_verification(self):
        self.assertNotIn('tokens', self.register('/api/register/instructor/').data)

    def test_correct_otp_verifies_email_keeps_professional_pending_and_issues_usable_tokens(self):
        self.register()
        response = self.verify(email='INSTRUCTOR@EXAMPLE.COM')
        self.assertEqual(response.status_code, 200, response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)
        self.assertEqual(self.user.verification_status, 'pending')
        self.assertIsNone(self.user.verified_at)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + response.data['tokens']['access'])
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 200)

    def test_minimal_signup_then_verification_preserves_deferred_profile_and_new_me_structure(self):
        self.payload = {key: self.payload[key] for key in (
            'email', 'name', 'password', 'confirm_password', 'gender', 'dob',
        )}
        self.register()
        profile = self.user.instructor_profile
        self.assertIsNone(profile.province_id)
        self.assertIsNone(profile.experience_years)
        self.assertEqual(profile.qualification, '')
        # Preserve upstream's existing onboarding flag; email verification is separate.
        self.assertTrue(self.user.onboarding_completed)
        verified = self.verify()
        self.assertEqual(verified.status_code, 200)
        tokens = verified.data['tokens']
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + tokens['access'])
        me = self.client.get('/api/v1/me/').data
        self.assertTrue(me['email_verified'])
        self.assertEqual(me['verification_status'], 'pending')
        for key in ('gender', 'dob', 'phone_number', 'province_id', 'qualification',
                    'cv_resume_url', 'certificates_and_recommendations_urls'):
            self.assertIn(key, me)
        self.assertIsNone(me['qualification'])
        municipality = Municipality.objects.select_related('district__province').get(name='OTP municipality')
        completed = self.client.post('/api/v1/instructor/complete-profile/', {
            'province_id': municipality.district.province_id,
            'district_id': municipality.district_id, 'municipality_id': municipality.pk,
            'phone_country_code': '+977', 'phone_number': '9812345678', 'location': 'Kirtipur',
            'qualification': 'Masters', 'subject_expertise': 'Physics', 'experience_years': 5,
        }, format='json')
        self.assertEqual(completed.status_code, 200, completed.data)
        me = self.client.get('/api/v1/me/').data
        self.assertEqual(me['qualification'], 'Masters')
        self.assertEqual(me['experience_years'], 5)
        self.assertTrue(me['email_verified'])
        self.assertEqual(me['verification_status'], 'pending')
        changed = self.client.patch('/api/v1/me/', {'name': 'Updated instructor'}, format='json')
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.data['name'], 'Updated instructor')
        self.assertTrue(changed.data['email_verified'])
        self.client.credentials()
        login = self.client.post('/api/v1/login/', {
            'email': self.user.email, 'password': self.payload['password'],
        }, format='json')
        self.assertEqual(login.status_code, 200)
        refreshed = self.client.post('/api/v1/token/refresh/', {'refresh': tokens['refresh']}, format='json')
        self.assertEqual(refreshed.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + refreshed.data['access'])
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 200)

    def test_web_login_rejects_unverified_then_accepts_verified_instructor(self):
        self.register()
        with patch('core.views.render', return_value=HttpResponse('login')):
            response = self.client.post('/login', {
                'email': self.user.email, 'password': self.payload['password'],
            })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.verify().status_code, 200)
        response = self.client.post('/login', {
            'email': self.user.email, 'password': self.payload['password'],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session['_auth_user_id'], str(self.user.pk))

    def test_wrong_otp_fails_and_attempts_are_limited(self):
        self.register()
        wrong = '0000' if self.otp != '0000' else '0001'
        for _ in range(5):
            self.assertEqual(self.verify(wrong).status_code, 400)
        self.assertEqual(self.verify().status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)
        self.assertTrue(self.user.instructor_signup_otps.get().is_used)

    def test_expired_otp_fails(self):
        self.register()
        self.user.instructor_signup_otps.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify().status_code, 400)

    def test_resend_invalidates_old_code_and_new_code_verifies(self):
        with patch('core.signup_otp.secrets.randbelow', return_value=123):
            self.register()
        old_record = self.user.instructor_signup_otps.get()
        self.allow_resend()
        with patch('core.signup_otp.secrets.randbelow', return_value=456):
            response = self.client.post(self.resend_url, {'email': self.user.email}, format='json')
        self.assertEqual(response.status_code, 200)
        old_record.refresh_from_db()
        self.assertTrue(old_record.is_used)
        self.assertEqual(self.verify('0123').status_code, 400)
        self.assertEqual(self.verify('0456').status_code, 200)

    def test_resend_cooldown_and_safe_unknown_verified_responses(self):
        self.register()
        initial = self.client.post(self.resend_url, {'email': self.user.email}, format='json')
        unknown = self.client.post(self.resend_url, {'email': 'unknown@example.com'}, format='json')
        self.assertEqual(initial.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.user.instructor_signup_otps.count(), 1)
        self.verify()
        verified = self.client.post(self.resend_url, {'email': self.user.email}, format='json')
        self.assertEqual(initial.data, verified.data)
        self.assertEqual(len(mail.outbox), 1)

    def test_otp_is_single_use_and_malformed_codes_fail(self):
        self.register()
        for code in ['123', '12345', 'abcd', '１２３４']:
            self.assertEqual(self.verify(code).status_code, 400)
        self.assertEqual(self.verify().status_code, 200)
        self.assertEqual(self.verify().status_code, 400)

    def test_unverified_login_access_and_refresh_are_blocked(self):
        self.register()
        self.assertEqual(self.client.post('/api/v1/login/', {
            'email': self.user.email, 'password': self.payload['password'],
        }, format='json').status_code, 400)
        token = RefreshToken.for_user(self.user)
        self.assertEqual(self.client.post('/api/v1/token/refresh/', {
            'refresh': str(token),
        }, format='json').status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(token.access_token))
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 401)
        self.assertEqual(self.client.get('/api/v1/courses/').status_code, 401)

    def test_inactive_account_cannot_verify_or_resend(self):
        self.register()
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertEqual(self.verify().status_code, 400)
        self.allow_resend()
        self.client.post(self.resend_url, {'email': self.user.email}, format='json')
        self.assertEqual(len(mail.outbox), 1)

    def test_email_failure_rolls_back_registration_and_resend(self):
        with patch('core.signup_otp.send_mail', side_effect=RuntimeError('Email unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/v1/register/instructor/', self.payload, format='json')
        self.assertFalse(User.objects.filter(email=self.payload['email']).exists())
        self.register()
        self.allow_resend()
        with patch('core.signup_otp.send_mail', side_effect=RuntimeError('Email unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.post(self.resend_url, {'email': self.user.email}, format='json')
        self.assertEqual(self.user.instructor_signup_otps.count(), 1)
        self.assertFalse(self.user.instructor_signup_otps.get().is_used)

    def test_existing_instructor_default_remains_usable(self):
        user = User.objects.create_user(
            email='legacy@example.com', password=self.payload['password'], name='Legacy',
            role=Role.objects.get(name='instructor'), verification_status='pending',
        )
        self.assertTrue(user.email_verified)
        response = self.client.post('/api/v1/login/', {
            'email': user.email, 'password': self.payload['password'],
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('tokens', response.data)

    def test_password_reset_stays_six_digits_and_does_not_verify_signup(self):
        self.register()
        self.client.post('/api/v1/forgot-password/', {'email': self.user.email}, format='json')
        reset_otp = re.search(r'OTP is ([0-9]{6})\.', mail.outbox[-1].body).group(1)
        self.assertEqual(self.verify(reset_otp).status_code, 400)
        record = PasswordResetOTP.objects.get(user=self.user)
        self.assertTrue(check_password(reset_otp, record.otp_hash))
        response = self.client.post('/api/v1/forgot-password/verify-otp/', {
            'email': self.user.email, 'otp': reset_otp,
        }, format='json')
        self.assertEqual(response.status_code, 200)
        response = self.client.post('/api/v1/forgot-password/reset/', {
            'reset_token': response.data['reset_token'], 'new_password': 'Another-strong-password-456',
            'confirm_password': 'Another-strong-password-456',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)
        self.assertTrue(self.user.check_password('Another-strong-password-456'))
        self.assertEqual(self.verify().status_code, 200)

    def test_student_registration_remains_immediately_authenticated(self):
        payload = dict(self.payload, email='student@example.com')
        response = self.client.post('/api/v1/register/student/', payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertIn('tokens', response.data)
        self.assertNotIn('email_verification_required', response.data)
        self.assertEqual(InstructorSignupOTP.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)


class InstructorEmailMigrationTests(TransactionTestCase):
    def test_preexisting_instructor_is_grandfathered_by_migration(self):
        before = [('core', '0033_reward_alter_pointtransaction_event_type_redemption')]
        after = [('core', '0034_instructor_signup_email_otp')]
        executor = MigrationExecutor(connection)
        self.assertEqual(executor.loader.graph.leaf_nodes('core'), after)
        executor.migrate(before)
        try:
            old_apps = executor.loader.project_state(before).apps
            role = old_apps.get_model('core', 'Role').objects.get(name='instructor')
            legacy = old_apps.get_model('core', 'User').objects.create(
                email='migration-legacy@example.com', name='Legacy', role=role,
                password='legacy-hash', verification_status='pending',
            )
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            migrated = executor.loader.project_state(after).apps.get_model('core', 'User').objects.get(pk=legacy.pk)
            self.assertTrue(migrated.email_verified)
            self.assertEqual(migrated.verification_status, 'pending')
        finally:
            MigrationExecutor(connection).migrate(after)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
class InstructorSignupOTPLiveTests(LiveServerTestCase):
    """Exercise the integrated signup contract through real local HTTP requests."""

    def setUp(self):
        cache.clear()
        Role.objects.get_or_create(name='instructor')
        Role.objects.get_or_create(name='student')
        self.payload = {
            'email': 'integrated-live@example.com', 'name': 'Integrated instructor',
            'password': 'A-strong-password-123', 'confirm_password': 'A-strong-password-123',
            'gender': 'other', 'dob': '1990-01-01',
        }

    def request(self, path, payload=None, token=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(
            self.live_server_url + '/api/v1/' + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers, method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def console_request(self, path, payload):
        console = StringIO()
        with redirect_stdout(console):
            response = self.request(path, payload)
        codes = re.findall(r'Your SkillSikka signup OTP is ([0-9]{4})\.', console.getvalue())
        return response, codes

    def test_integrated_http_signup_me_login_refresh_resend_and_student_regression(self):
        (status, body), codes = self.console_request('register/instructor/', self.payload)
        self.assertEqual(status, 201)
        self.assertFalse(body['user']['email_verified'])
        self.assertEqual(body['user']['verification_status'], 'pending')
        self.assertTrue(body['email_verification_required'])
        self.assertNotIn('tokens', body)
        self.assertEqual(len(codes), 1)
        otp = codes[0]
        wrong = '0000' if otp != '0000' else '0001'
        self.assertEqual(self.request('login/', {
            'email': self.payload['email'], 'password': self.payload['password'],
        })[0], 400)
        user = User.objects.get(email=self.payload['email'])
        self.assertIsNone(user.instructor_profile.experience_years)
        probe = RefreshToken.for_user(user)
        self.assertEqual(self.request('me/', token=str(probe.access_token))[0], 401)
        self.assertEqual(self.request('token/refresh/', {'refresh': str(probe)})[0], 401)
        status, body = self.request('register/instructor/verify-otp/', {'email': user.email, 'otp': wrong})
        self.assertEqual(status, 400)
        self.assertNotIn('tokens', body)
        status, body = self.request('register/instructor/verify-otp/', {'email': user.email, 'otp': otp})
        self.assertEqual(status, 200)
        self.assertTrue(body['user']['email_verified'])
        self.assertEqual(body['user']['verification_status'], 'pending')
        access, refresh = body['tokens']['access'], body['tokens']['refresh']
        status, body = self.request('me/', token=access)
        self.assertEqual(status, 200)
        self.assertTrue(body['email_verified'])
        self.assertIn('cv_resume_url', body)
        self.assertIsNone(body['qualification'])
        status, body = self.request('me/', {'name': 'Updated via HTTP'}, token=access, method='PATCH')
        self.assertEqual(status, 200)
        self.assertTrue(body['email_verified'])
        self.assertEqual(body['name'], 'Updated via HTTP')
        self.assertEqual(self.request('login/', {'email': user.email, 'password': self.payload['password']})[0], 200)
        self.assertEqual(self.request('token/refresh/', {'refresh': refresh})[0], 200)

        resend_payload = dict(self.payload, email='integrated-resend@example.com')
        (status, body), codes = self.console_request('register/instructor/', resend_payload)
        self.assertEqual(status, 201)
        old_otp = codes[0]
        (status, body), codes = self.console_request('register/instructor/resend-otp/', {'email': resend_payload['email']})
        self.assertEqual(status, 200)
        self.assertEqual(codes, [])
        resend_user = User.objects.get(email=resend_payload['email'])
        # Simulate elapsed cooldown on this disposable test database only.
        resend_user.instructor_signup_otps.update(created_at=timezone.now() - timedelta(seconds=61))
        replacement = (int(old_otp) + 1) % 10000
        with patch('core.signup_otp.secrets.randbelow', return_value=replacement):
            (status, body), codes = self.console_request('register/instructor/resend-otp/', {'email': resend_user.email})
        self.assertEqual(status, 200)
        new_otp = codes[0]
        self.assertEqual(self.request('register/instructor/verify-otp/', {'email': resend_user.email, 'otp': old_otp})[0], 400)
        self.assertEqual(self.request('register/instructor/verify-otp/', {'email': resend_user.email, 'otp': new_otp})[0], 200)

        status, body = self.request('register/student/', dict(self.payload, email='integrated-student@example.com'))
        self.assertEqual(status, 201)
        self.assertIn('tokens', body)
        self.assertNotIn('email_verification_required', body)
        self.assertEqual(self.request('me/', token=body['tokens']['access'])[0], 200)
        self.assertEqual(self.request('login/', {
            'email': 'integrated-student@example.com', 'password': self.payload['password'],
        })[0], 200)
