from django.test import TestCase
from django.urls import reverse

from .models import District, Grade, InstructorProfile, Municipality, Permission, Province, Role, School, StudentProfile, User


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
