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
