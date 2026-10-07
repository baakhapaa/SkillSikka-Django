import importlib
import json
import re
from types import SimpleNamespace
import urllib.error
import urllib.request
from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.core import mail
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import LiveServerTestCase, TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .models import District, Grade, LearningInterest, Municipality, Province, Role, School, StudentProfile, User


EXPECTED_INTERESTS = [
    ('Coding', 'coding'), ('Mathematics', 'mathematics'), ('Physics', 'physics'),
    ('Chemistry', 'chemistry'), ('Biology', 'biology'), ('Data Science', 'data-science'),
    ('AI & ML', 'ai-ml'), ('Web Dev', 'web-dev'), ('App Dev', 'app-dev'),
    ('Robotics', 'robotics'), ('Electronics', 'electronics'), ('3D Design', '3d-design'),
]


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class StudentLearningInterestsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.throttles = patch('rest_framework.views.APIView.check_throttles')
        self.throttles.start()
        self.addCleanup(self.throttles.stop)
        self.payload = {
            'email': 'interests-student@example.com', 'name': 'Student',
            'password': 'A-strong-password-123', 'confirm_password': 'A-strong-password-123',
            'gender': 'other', 'dob': '2010-01-01',
        }
        response = self.client.post('/api/v1/register/student/', self.payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.registration = response.data
        self.student = User.objects.get(email=self.payload['email'])
        otp = re.search(r'OTP is ([0-9]{4})\.', mail.outbox[-1].body).group(1)
        response = self.client.post('/api/v1/register/student/verify-otp/', {'email':self.student.email,'otp':otp}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.student.refresh_from_db()
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + response.data['tokens']['access'])
        self.ids = list(LearningInterest.objects.values_list('id', flat=True))
        province = Province.objects.create(name='Interest test province')
        district = District.objects.create(name='Interest test district', province=province)
        municipality = Municipality.objects.create(name='Interest test municipality', district=district)
        school = School.objects.create(name='Interest test school', municipality=municipality, sector='public')
        grade = Grade.objects.create(name='Interest test grade')
        self.profile_payload = {
            'phone_country_code': '+977', 'phone_number': '9800000000', 'location': 'Kathmandu',
            'grade_id': grade.pk, 'province_id': province.pk, 'district_id': district.pk,
            'school_id': school.pk,
        }

    def select(self, ids=None, **extra):
        return self.client.put('/api/v1/me/learning-interests/',
                               dict(interest_ids=self.ids[:3] if ids is None else ids, **extra), format='json')

    def complete_profile(self):
        return self.client.post('/api/v1/me/complete-profile/', self.profile_payload, format='json')

    def test_seeded_catalogue_is_exact_and_ordered(self):
        self.assertEqual(list(LearningInterest.objects.values_list('name', 'slug')), EXPECTED_INTERESTS)
        self.assertEqual(list(LearningInterest.objects.values_list('display_order', flat=True)), list(range(1, 13)))
        response = self.client.get('/api/v1/learning-interests/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([(i['name'], i['slug']) for i in response.data], EXPECTED_INTERESTS)
        self.assertEqual(set(response.data[0]), {'id', 'name', 'slug', 'description', 'display_order'})

    def test_new_registration_requires_email_verification_and_enables_new_flow(self):
        self.assertNotIn('tokens', self.registration)
        self.assertTrue(self.registration['email_verification_required'])
        self.assertTrue(self.student.email_verified)
        self.assertEqual(self.student.student_profile.onboarding_flow_version, 2)
        self.assertFalse(self.student.onboarding_completed)
        self.assertEqual(self.student.onboarding_step, 2)
        self.assertEqual(self.client.get('/api/v1/me/').status_code, 200)

    def test_profile_without_interests_remains_incomplete_at_step_four(self):
        response = self.complete_profile()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['profile_completed'])
        self.assertFalse(response.data['learning_interests_completed'])
        self.assertFalse(response.data['onboarding_completed'])
        self.assertEqual(response.data['onboarding_step'], 4)
        self.student.refresh_from_db()
        self.assertFalse(self.student.onboarding_completed)
        self.assertTrue(self.student.student_profile.profile_completed)

    def test_interests_without_profile_do_not_complete_onboarding(self):
        response = self.select(self.ids[:4])
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['interests_completed'])
        self.assertFalse(response.data['profile_completed'])
        self.assertFalse(response.data['onboarding_completed'])
        self.assertEqual(response.data['onboarding_step'], 2)

    def test_profile_first_interests_second_completes_onboarding(self):
        self.complete_profile()
        response = self.select()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['onboarding_completed'])
        self.assertEqual(response.data['onboarding_step'], 4)
        self.student.refresh_from_db()
        self.assertTrue(self.student.onboarding_completed)

    def test_interests_first_profile_second_completes_onboarding(self):
        self.select()
        response = self.complete_profile()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['onboarding_completed'])
        self.assertTrue(response.data['learning_interests_completed'])
        self.assertEqual(response.data['onboarding_step'], 4)

    def test_invalid_selections_preserve_previous_selection_and_state(self):
        self.complete_profile()
        self.assertEqual(self.select().status_code, 200)
        inactive = LearningInterest.objects.get(pk=self.ids[4])
        inactive.is_active = False
        inactive.save(update_fields=['is_active'])
        for ids in [[], self.ids[:2], [self.ids[0]] * 3, self.ids[:2] + [999999],
                    self.ids[:2] + [inactive.pk], '1,2,3', None, [0, 1, 2]]:
            with self.subTest(ids=ids):
                response = self.client.put('/api/v1/me/learning-interests/', {'interest_ids': ids}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn('interest_ids', response.data)
                self.assertEqual(list(self.student.student_profile.learning_interests.values_list('id', flat=True)), self.ids[:3])
                self.student.refresh_from_db()
                self.assertTrue(self.student.onboarding_completed)

    def test_missing_ids_and_non_object_body_are_rejected(self):
        for payload in [{}, [], {'interest_ids': {'a': 1}}]:
            self.assertEqual(self.client.put('/api/v1/me/learning-interests/', payload, format='json').status_code, 400)

    def test_put_replaces_selection_and_get_returns_contract(self):
        self.select()
        response = self.select(self.ids[3:6])
        self.assertEqual(response.status_code, 200)
        get = self.client.get('/api/v1/me/learning-interests/')
        self.assertEqual(get.status_code, 200)
        self.assertEqual([i['id'] for i in get.data['learning_interests']], self.ids[3:6])
        self.assertEqual(get.data['selected_count'], 3)
        self.assertEqual(get.data['minimum_required'], 3)
        self.assertTrue(get.data['interests_completed'])
        self.assertFalse(get.data['profile_completed'])

    def test_replacement_rolls_back_if_state_save_fails(self):
        self.select()
        with patch.object(User, 'save', side_effect=RuntimeError('Simulated state save failure')):
            with self.assertRaises(RuntimeError):
                self.select(self.ids[3:6])
        self.assertEqual(list(self.student.student_profile.learning_interests.values_list('id', flat=True)), self.ids[:3])

    def test_selected_inactive_interest_remains_visible_and_can_be_retained(self):
        self.complete_profile()
        self.select()
        LearningInterest.objects.filter(pk=self.ids[0]).update(is_active=False)
        response = self.client.get('/api/v1/me/learning-interests/')
        self.assertEqual(response.data['selected_count'], 3)
        self.assertFalse(response.data['learning_interests'][0]['is_active'])
        self.assertTrue(response.data['interests_completed'])
        self.assertTrue(response.data['onboarding_completed'])
        self.assertEqual(self.select().status_code, 200)
        catalogue = self.client.get('/api/v1/learning-interests/').data
        self.assertNotIn(self.ids[0], [i['id'] for i in catalogue])
        # Once removed, an inactive interest cannot be added back as a new selection.
        self.select(self.ids[3:6])
        self.assertEqual(self.select().status_code, 400)

    def test_catalogue_orders_ties_by_id(self):
        LearningInterest.objects.filter(pk__in=self.ids[:2]).update(display_order=1)
        self.assertEqual([i['id'] for i in self.client.get('/api/v1/learning-interests/').data[:2]], self.ids[:2])

    def test_me_get_and_patch_preserve_fields_and_expose_interests(self):
        self.complete_profile()
        self.select()
        for response in [self.client.get('/api/v1/me/'), self.client.patch('/api/v1/me/', {'name': 'Renamed'}, format='json')]:
            self.assertEqual(response.status_code, 200)
            data = response.data
            self.assertEqual(len(data['learning_interests']), 3)
            self.assertTrue(data['learning_interests_completed'])
            self.assertTrue(data['profile_completed'])
            self.assertTrue(data['onboarding_completed'])
            self.assertEqual(data['onboarding_step'], 4)
            for key in ['email_verified', 'gender', 'dob', 'grade_id', 'school_id', 'student_id_card_url']:
                self.assertIn(key, data)

    def test_no_cross_user_selection_or_ownership_input(self):
        other = User.objects.create_user(email='other@example.com', name='Other', role=Role.objects.get(name='student'))
        StudentProfile.objects.create(user=other)
        self.assertEqual(self.select(student_id=other.pk).status_code, 400)
        self.assertEqual(self.select(user_id=other.pk).status_code, 400)
        self.select()
        self.assertEqual(other.student_profile.learning_interests.count(), 0)

    def test_instructor_is_rejected_and_me_contract_is_unchanged(self):
        instructor = User.objects.create_user(email='instructor@example.com', name='Instructor', role=Role.objects.get(name='instructor'))
        token = RefreshToken.for_user(instructor)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(token.access_token))
        self.assertEqual(self.client.get('/api/v1/me/learning-interests/').status_code, 403)
        self.assertEqual(self.select().status_code, 403)
        response = self.client.get('/api/v1/me/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('learning_interests', response.data)
        self.assertEqual(response.data['onboarding_completed'], instructor.onboarding_completed)

    def test_unauthenticated_requests_are_rejected(self):
        self.client.credentials()
        self.assertEqual(self.client.get('/api/v1/learning-interests/').status_code, 401)
        self.assertEqual(self.client.get('/api/v1/me/learning-interests/').status_code, 401)
        self.assertEqual(self.select().status_code, 401)

    def legacy_student(self, completed):
        user = User.objects.create_user(
            email='legacy@example.com', name='Legacy', role=Role.objects.get(name='student'),
            onboarding_completed=completed, onboarding_step=3,
        )
        StudentProfile.objects.create(user=user, profile_completed=completed)
        token = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + str(token.access_token))
        return user

    def test_completed_legacy_student_keeps_completion_without_interests(self):
        user = self.legacy_student(True)
        response = self.client.get('/api/v1/me/learning-interests/')
        self.assertTrue(response.data['onboarding_completed'])
        self.assertFalse(response.data['interests_completed'])
        self.assertEqual(response.data['onboarding_flow_version'], 1)
        self.assertEqual(response.data['onboarding_step'], 3)
        self.assertTrue(self.complete_profile().data['onboarding_completed'])
        user.refresh_from_db()
        self.assertTrue(user.onboarding_completed)

    def test_incomplete_legacy_student_keeps_old_profile_completion(self):
        user = self.legacy_student(False)
        self.assertFalse(self.client.get('/api/v1/me/').data['onboarding_completed'])
        self.assertFalse(self.select().data['onboarding_completed'])
        self.assertTrue(self.complete_profile().data['onboarding_completed'])
        user.refresh_from_db()
        self.assertEqual(user.onboarding_step, 3)

    def test_legacy_profile_completion_requires_no_interests(self):
        user = self.legacy_student(False)
        response = self.complete_profile()
        self.assertTrue(response.data['onboarding_completed'])
        self.assertFalse(response.data['learning_interests_completed'])
        self.assertEqual(user.student_profile.learning_interests.count(), 0)

    def test_invalid_profile_does_not_complete_profile_stage(self):
        response = self.client.post('/api/v1/me/complete-profile/', {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.student.student_profile.profile_completed)
        self.select()
        self.assertFalse(self.client.get('/api/v1/me/').data['onboarding_completed'])


class LearningInterestMigrationTests(TransactionTestCase):
    def test_legacy_flags_steps_and_data_are_preserved_and_seed_is_idempotent(self):
        before = [('core', '0034_instructor_signup_email_otp')]
        after = [('core', '0036_seed_learning_interests')]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes('core')
        executor.migrate(before)
        try:
            old = executor.loader.project_state(before).apps
            role, _ = old.get_model('core', 'Role').objects.get_or_create(name='student')
            for completed in (False, True):
                user = old.get_model('core', 'User').objects.create(
                    name='Legacy', email=f'legacy-{completed}@example.com', role=role,
                    onboarding_completed=completed, onboarding_step=3,
                )
                old.get_model('core', 'StudentProfile').objects.create(user=user)
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            new = executor.loader.project_state(after).apps
            for completed in (False, True):
                user = new.get_model('core', 'User').objects.get(email=f'legacy-{completed}@example.com')
                profile = new.get_model('core', 'StudentProfile').objects.get(user_id=user.pk)
                self.assertEqual(user.onboarding_completed, completed)
                self.assertEqual(user.onboarding_step, 3)
                self.assertEqual(profile.onboarding_flow_version, 1)
                self.assertEqual(profile.profile_completed, completed)
                self.assertEqual(profile.learning_interests.count(), 0)
            seed = importlib.import_module('core.migrations.0036_seed_learning_interests')
            seed.seed_interests_and_profile_stage(new, SimpleNamespace(connection=connection))
            self.assertEqual(new.get_model('core', 'LearningInterest').objects.count(), 12)
        finally:
            MigrationExecutor(connection).migrate(latest)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class StudentLearningInterestsLiveTests(LiveServerTestCase):
    def setUp(self):
        cache.clear()
        Role.objects.get_or_create(name='student')
        seed = importlib.import_module('core.migrations.0036_seed_learning_interests')
        seed.seed_interests_and_profile_stage(apps, SimpleNamespace(connection=connection))
        province = Province.objects.create(name='Live interest province')
        district = District.objects.create(name='Live interest district', province=province)
        municipality = Municipality.objects.create(name='Live interest municipality', district=district)
        school = School.objects.create(name='Live interest school', municipality=municipality, sector='public')
        grade = Grade.objects.create(name='Live interest grade')
        self.profile_payload = {
            'phone_country_code': '+977', 'phone_number': '9800000000', 'location': 'Kathmandu',
            'grade_id': grade.pk, 'province_id': province.pk, 'district_id': district.pk, 'school_id': school.pk,
        }

    def request(self, path, payload=None, token=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(self.live_server_url + '/api/v1/' + path,
            data=json.dumps(payload).encode() if payload is not None else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_real_http_register_profile_catalogue_select_me(self):
        status, body = self.request('register/student/', {
            'email': 'live-interest@example.com', 'name': 'Live student',
            'password': 'A-strong-password-123', 'confirm_password': 'A-strong-password-123',
            'gender': 'other', 'dob': '2010-01-01',
        })
        self.assertEqual(status, 201)
        self.assertNotIn('tokens', body)
        otp = re.search(r'OTP is ([0-9]{4})\.', mail.outbox[-1].body).group(1)
        status, body = self.request('register/student/verify-otp/', {'email':'live-interest@example.com','otp':otp})
        self.assertEqual(status, 200)
        token = body['tokens']['access']
        status, body = self.request('me/complete-profile/', self.profile_payload, token)
        self.assertEqual(status, 200)
        self.assertTrue(body['profile_completed'])
        self.assertFalse(body['onboarding_completed'])
        self.assertEqual(body['onboarding_step'], 4)
        status, catalogue = self.request('learning-interests/', token=token)
        self.assertEqual(status, 200)
        self.assertEqual(len(catalogue), 12)
        ids = [item['id'] for item in catalogue[:3]]
        status, body = self.request('me/learning-interests/', {'interest_ids': ids}, token, method='PUT')
        self.assertEqual(status, 200)
        self.assertTrue(body['onboarding_completed'])
        status, body = self.request('me/', token=token)
        self.assertEqual(status, 200)
        self.assertEqual([i['id'] for i in body['learning_interests']], ids)
        self.assertTrue(body['learning_interests_completed'])
        self.assertTrue(body['profile_completed'])
        self.assertTrue(body['onboarding_completed'])
        self.assertEqual(body['onboarding_step'], 4)
