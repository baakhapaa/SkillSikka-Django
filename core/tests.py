import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import District, Grade, InstructorProfile, Municipality, Permission, Province, Role, School, StudentProfile, User, VerificationDocument


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
		self.province = Province.objects.create(name='Bagmati')
		self.district = District.objects.create(name='Kathmandu', province=self.province)
		self.municipality = Municipality.objects.create(name='Kirtipur', district=self.district)
		self.school = School.objects.create(name='SkillSikka Academy', municipality=self.municipality, sector='private')
		self.grade = Grade.objects.create(name='Grade 8')

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

	def test_student_registration_creates_pending_profile_without_optional_school(self):
		response = self.client.post('/api/v1/register/student/', self.student_payload(), content_type='application/json')
		self.assertEqual(response.status_code, 201)
		user = User.objects.get(email='student@example.com')
		self.assertTrue(StudentProfile.objects.filter(user=user, school=None, grade=self.grade).exists())
		self.assertEqual(user.role.name, 'student')
		self.assertEqual(user.verification_status, 'pending')

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
			'profile_photo': SimpleUploadedFile('me.png', b'png-bytes', content_type='image/png'),
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
			'cv_resume': SimpleUploadedFile('cv.pdf', b'cv', content_type='application/pdf'),
			'certificates_and_recommendations': [
				SimpleUploadedFile('a.pdf', b'a', content_type='application/pdf'),
				SimpleUploadedFile('b.pdf', b'b', content_type='application/pdf'),
			],
		}, format='multipart')
		self.assertEqual(response.status_code, 200, response.content)
		data = response.json()
		self.assertIsNotNone(data['cv_resume_url'])
		self.assertEqual(len(data['certificates_and_recommendations_urls']), 2)

	def test_document_slots_are_role_specific(self):
		self.client.force_authenticate(self.instructor)
		response = self.client.patch('/api/v1/me/', {
			'student_id_card': SimpleUploadedFile('card.pdf', b'x', content_type='application/pdf'),
		}, format='multipart')
		self.assertEqual(response.status_code, 400)
		self.assertIn('student_id_card', response.json())

	def test_oversized_profile_photo_is_rejected(self):
		self.client.force_authenticate(self.student)
		big = SimpleUploadedFile('big.png', b'0' * (5 * 1024 * 1024 + 1), content_type='image/png')
		response = self.client.patch('/api/v1/me/', {'profile_photo': big}, format='multipart')
		self.assertEqual(response.status_code, 400)
		self.assertIn('profile_photo', response.json())
