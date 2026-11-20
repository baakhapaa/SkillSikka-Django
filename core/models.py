import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from .book_files import (
    PrivateBookStorage, book_cover_path, book_source_path,
    validate_book_cover, validate_book_source, validate_highlights,
)


class Role(models.Model):
	name = models.CharField(max_length=40, unique=True)
	description = models.TextField(blank=True)

	class Meta:
		db_table = 'roles'

	def __str__(self):
		return self.name


class Permission(models.Model):
	name = models.CharField(max_length=80, unique=True)
	description = models.TextField(blank=True)

	class Meta:
		db_table = 'permissions'

	def __str__(self):
		return self.name


class RolePermission(models.Model):
	role = models.ForeignKey(
		Role,
		on_delete=models.CASCADE,
		related_name='role_permissions'
	)
	permission = models.ForeignKey(
		Permission,
		on_delete=models.CASCADE,
		related_name='role_permissions'
	)

	class Meta:
		db_table = 'rolepermissions'
		constraints = [
			models.UniqueConstraint(
				fields=['role', 'permission'],
				name='unique_role_permission'
			),
		]


class Province(models.Model):
	name = models.CharField(max_length=150, unique=True)

	class Meta:
		db_table = 'provinces'

	def __str__(self):
		return self.name


class District(models.Model):
	name = models.CharField(max_length=150)
	province = models.ForeignKey(
		Province,
		on_delete=models.CASCADE,
		related_name='districts'
	)

	class Meta:
		db_table = 'districts'
		constraints = [
			models.UniqueConstraint(
				fields=['province', 'name'],
				name='unique_district_per_province'
			),
		]

	def __str__(self):
		return self.name


class Municipality(models.Model):
	name = models.CharField(max_length=150)
	district = models.ForeignKey(
		District,
		on_delete=models.CASCADE,
		related_name='municipalities'
	)

	class Meta:
		db_table = 'municipalities'
		constraints = [
			models.UniqueConstraint(
				fields=['district', 'name'],
				name='unique_municipality_per_district'
			),
		]

	def __str__(self):
		return self.name


class School(models.Model):
	SECTOR_CHOICES = (
		('public', 'Public'),
		('private', 'Private'),
	)

	name = models.CharField(max_length=200)
	logo_url = models.URLField(blank=True)
	brand_colors = models.JSONField(default=dict, blank=True)
	sector = models.CharField(
		max_length=10,
		choices=SECTOR_CHOICES
	)
	municipality = models.ForeignKey(
		Municipality,
		on_delete=models.PROTECT,
		related_name='schools'
	)

	class Meta:
		db_table = 'schools'

	def __str__(self):
		return self.name


class Grade(models.Model):
	name = models.CharField(max_length=100, unique=True)

	class Meta:
		db_table = 'grades'

	def __str__(self):
		return self.name


class UserManager(BaseUserManager):
	def create_user(self, email, password=None, **extra_fields):
		if not email:
			raise ValueError('An email address is required.')

		if not extra_fields.get('role'):
			raise ValueError('A role is required.')

		user = self.model(
			email=self.normalize_email(email),
			**extra_fields
		)

		if password:
			user.set_password(password)
		else:
			user.set_unusable_password()

		user.save(using=self._db)
		return user

	def create_superuser(self, email, password=None, **extra_fields):
		if 'role' not in extra_fields:
			extra_fields['role'] = Role.objects.get(
				name='super_admin'
			)

		extra_fields.setdefault('is_staff', True)
		extra_fields.setdefault('is_superuser', True)
		extra_fields.setdefault('onboarding_completed', True)
		extra_fields.setdefault('is_active', True)

		return self.create_user(
			email,
			password,
			**extra_fields
		)


class User(AbstractBaseUser, PermissionsMixin):
	VERIFICATION_CHOICES = (
		('not_applicable', 'Not applicable'),
		('pending', 'Pending'),
		('verified', 'Verified'),
		('rejected', 'Rejected'),
	)

	name = models.CharField(max_length=150)
	email = models.EmailField(unique=True)

	phone_country_code = models.CharField(
		max_length=8,
		blank=True
	)
	phone_number = models.CharField(
		max_length=30,
		blank=True
	)

	role = models.ForeignKey(
		Role,
		on_delete=models.PROTECT,
		related_name='users'
	)

	profile_photo_url = models.URLField(blank=True)
	gender = models.CharField(max_length=10, blank=True)
	dob = models.DateField(null=True, blank=True)
	location = models.CharField(max_length=255, blank=True)

	onboarding_completed = models.BooleanField(default=False)
	# Legacy accounts remain usable; instructor signup explicitly sets False.
	email_verified = models.BooleanField(default=True)
	onboarding_step = models.PositiveSmallIntegerField(default=0)

	verification_status = models.CharField(
		max_length=20,
		choices=VERIFICATION_CHOICES,
		default='not_applicable'
	)

	verified_by = models.ForeignKey(
		'self',
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='verified_users'
	)

	verified_at = models.DateTimeField(
		null=True,
		blank=True
	)

	is_active = models.BooleanField(default=True)
	is_staff = models.BooleanField(default=False)

	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	objects = UserManager()

	USERNAME_FIELD = 'email'
	REQUIRED_FIELDS = ['name']

	class Meta:
		db_table = 'users'

	def __str__(self):
		return self.name or self.email

	def has_role_permission(self, permission_name):
		if self.is_superuser:
			return True

		return bool(
			self.role
			and self.role.role_permissions.filter(
				permission__name=permission_name
			).exists()
		)

	@property
	def profile_photo_src(self):
		# profile_photo_url holds a storage name (older rows: a URL); resolve
		# it on read so the URL never goes stale, e.g. signed S3 links.
		from .documents import media_src
		return media_src(self.profile_photo_url)


class VerificationDocument(models.Model):
	DOCUMENT_TYPE_CHOICES = (
		('student_id_card', 'Student ID Card'),
		('cv_resume', 'CV / Resume'),
		('certificate', 'Certificate'),
		('recommendation_letter', 'Recommendation Letter'),
	)

	user = models.ForeignKey(
		User,
		on_delete=models.CASCADE,
		related_name='verification_documents'
	)

	document_type = models.CharField(
		max_length=30,
		choices=DOCUMENT_TYPE_CHOICES
	)

	file_url = models.CharField(max_length=500)
	uploaded_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'verification_documents'

	def __str__(self):
		return self.document_type


def advertisement_image_path(instance, filename):
	from pathlib import Path
	from uuid import uuid4
	return f'advertisements/{uuid4().hex}{Path(filename).suffix.lower()}'


class Advertisement(models.Model):
	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	banner_image = models.ImageField(upload_to=advertisement_image_path)
	cta_text = models.CharField(max_length=100, blank=True)
	cta_url = models.URLField(max_length=2048, blank=True)
	starts_at = models.DateTimeField(null=True, blank=True)
	ends_at = models.DateTimeField(null=True, blank=True)
	display_order = models.PositiveIntegerField(default=0)
	is_active = models.BooleanField(default=False)
	archived_at = models.DateTimeField(null=True, blank=True)
	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_advertisements')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'advertisements'
		ordering = ['display_order', 'id']
		constraints = [models.CheckConstraint(
			condition=models.Q(starts_at__isnull=True) | models.Q(ends_at__isnull=True) | models.Q(ends_at__gte=models.F('starts_at')),
			name='advertisement_valid_schedule',
		)]

	def __str__(self):
		return self.title


class LearningInterest(models.Model):
	name = models.CharField(max_length=150)
	slug = models.SlugField(max_length=150, unique=True)
	description = models.TextField(blank=True)
	display_order = models.PositiveSmallIntegerField(default=0)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'learning_interests'
		ordering = ['display_order', 'id']

	def __str__(self):
		return self.name


class PremiumCategory(models.Model):
	"""The category list a **premium** course is filed under.

	**Deliberately not `LearningInterest`.** That table is the student-facing
	skill taxonomy — the signup interests step, the Skill tab's chips and
	`/me/learning-interests/` all read it — so filing premium courses there would
	put "Business" in front of a student choosing what they want to learn. Premium
	is a paid tier with its own small set, seeded from the premium catalogue's own
	chips (Art & Craft, Design, Physics, Business, Technology, Music).

	Two lists, two tables. A premium course may not point at a skill category and
	a skill course may not point at one of these; `Course.clean()` and
	`CourseSerializer.validate` both enforce it.
	"""

	name = models.CharField(max_length=150)
	slug = models.SlugField(max_length=150, unique=True)
	display_order = models.PositiveSmallIntegerField(default=0)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'premium_categories'
		ordering = ['display_order', 'id']

	def __str__(self):
		return self.name


class StudentProfile(models.Model):
	LEGACY_ONBOARDING = 1
	INTERESTS_ONBOARDING = 2

	onboarding_flow_version = models.PositiveSmallIntegerField(
		choices=((1, 'Legacy'), (2, 'Learning interests')),
		default=LEGACY_ONBOARDING,
	)
	profile_completed = models.BooleanField(default=False)
	learning_interests = models.ManyToManyField(
		LearningInterest, blank=True, related_name='student_profiles',
	)
	user = models.OneToOneField(
		User,
		on_delete=models.CASCADE,
		primary_key=True,
		related_name='student_profile'
	)

	grade = models.ForeignKey(
		Grade,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='student_profiles'
	)

	province = models.ForeignKey(
		Province,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='student_profiles'
	)

	district = models.ForeignKey(
		District,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='student_profiles'
	)

	municipality = models.ForeignKey(
		Municipality,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='student_profiles'
	)

	school = models.ForeignKey(
		School,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='student_profiles'
	)

	student_id_card_document = models.ForeignKey(
		VerificationDocument,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='student_profiles',
	)

	available_sikka = models.IntegerField(default=0)
	total_earned_sikka = models.IntegerField(default=0)
	used_sikka = models.IntegerField(default=0)

	class Meta:
		db_table = 'student_profiles'


class InstructorProfile(models.Model):
	user = models.OneToOneField(
		User,
		on_delete=models.CASCADE,
		primary_key=True,
		related_name='instructor_profile'
	)

	province = models.ForeignKey(
		Province,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='instructor_profiles'
	)

	district = models.ForeignKey(
		District,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='instructor_profiles'
	)

	municipality = models.ForeignKey(
		Municipality,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='instructor_profiles'
	)

	school = models.ForeignKey(
		School,
		on_delete=models.PROTECT,
		null=True,
		blank=True,
		related_name='instructor_profiles'
	)

	qualification = models.CharField(max_length=255, blank=True, default='')
	subject_expertise = models.TextField(blank=True, default='')
	# The "Biography" paragraph on the public profile.
	bio = models.TextField(max_length=1000, blank=True, default='')

	experience_years = models.DecimalField(
		max_digits=5,
		decimal_places=2,
		null=True,
		blank=True,
	)

	cv_resume_document = models.ForeignKey(
		VerificationDocument,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='instructor_profiles',
	)

	class Meta:
		db_table = 'instructor_profiles'


class Subject(models.Model):
	name = models.CharField(max_length=150, unique=True)

	class Meta:
		db_table = 'subjects'

	def __str__(self):
		return self.name


class Chapter(models.Model):
	subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='chapters')
	grade = models.ForeignKey(Grade, on_delete=models.CASCADE, related_name='chapters')
	name = models.CharField(max_length=200)
	order = models.PositiveSmallIntegerField(default=0)

	class Meta:
		db_table = 'chapters'
		constraints = [
			models.UniqueConstraint(fields=['subject', 'grade', 'name'], name='unique_chapter_per_subject_grade'),
		]
		ordering = ['order']

	def __str__(self):
		return self.name


class CourseQuerySet(models.QuerySet):
	def with_access(self, user):
		return self.annotate(is_enrolled=models.Exists(Enrollment.objects.filter(
			student=user, course=models.OuterRef('pk'), status__in=['active', 'completed'],
		)))

	def with_review_stats(self):
		return self.with_card_stats().annotate(
			average_rating=models.Avg('reviews__rating'),
			review_count=models.Count('reviews', distinct=True),
		)

	def with_card_stats(self):
		lessons = Lesson.objects.filter(course=models.OuterRef('pk')).order_by().values('course')
		students = Enrollment.objects.filter(course=models.OuterRef('pk'), status__in=['active', 'completed']).order_by().values('course')
		return self.select_related('skill_category').annotate(
			students_enrolled=models.functions.Coalesce(models.Subquery(students.annotate(value=models.Count('student', distinct=True)).values('value')), 0),
			lessons_count=models.functions.Coalesce(models.Subquery(lessons.annotate(value=models.Count('pk')).values('value')), 0),
			total_duration_seconds=models.Subquery(lessons.annotate(value=models.Sum('duration_seconds')).values('value')),
		)


def with_instructor_review_stats(queryset=None):
	"""Review-weighted aggregate across all courses for instructor rankings.

	Pass a filtered User queryset to restrict instructors. Publication status
	does not invalidate historical reviews; rankings can apply a publication
	filter to the aggregate expressions if that product policy is desired.
	"""
	if queryset is None:
		queryset = User.objects.filter(role__name='instructor')
	return queryset.annotate(
		# Isolate reviews from any course/enrollment joins on the caller's
		# queryset so each review contributes exactly once to the average.
		average_rating=models.Subquery(
			CourseReview.objects.filter(course__instructor=models.OuterRef('pk'))
			.order_by().values('course__instructor')
			.annotate(value=models.Avg('rating')).values('value')
		),
		review_count=models.functions.Coalesce(models.Subquery(
			CourseReview.objects.filter(course__instructor=models.OuterRef('pk'))
			.order_by().values('course__instructor')
			.annotate(value=models.Count('pk')).values('value')
		), 0),
	)


class Course(models.Model):
	objects = CourseQuerySet.as_manager()
	COURSE_TYPE_CHOICES = (
		('academic', 'Academic'),
		('skill', 'Skill Development'),
		# **Premium is a paid skill course, not a fourth curriculum.** Same
		# authoring as `skill` — a category, no subject/grade, no placement test —
		# and the one difference is that it cannot be free. Enforced in `clean()`
		# and in `CourseSerializer.validate`; both paths exist because the API
		# writes rows without calling `full_clean`.
		('premium', 'Premium'),
		('bootcamp', 'Bootcamp'),
	)
	LEVEL_CHOICES = (
		('beginner', 'Beginner'),
		('intermediate', 'Intermediate'),
		('advanced', 'Advanced'),
	)

	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	instructor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='courses')
	learning_outcomes = models.JSONField(default=list, blank=True)
	requirements = models.JSONField(default=list, blank=True)
	course_type = models.CharField(max_length=10, choices=COURSE_TYPE_CHOICES)
	# Optional: an instructor who does not pick one gets no level row on the
	# student card rather than a wrong one.
	level = models.CharField(max_length=20, choices=LEVEL_CHOICES, blank=True, default='')
	# The language the lessons are taught in. One value, because the client
	# renders it as a single line; a course taught in several languages would
	# need an M2M, and no screen asks for that yet.
	language = models.CharField(max_length=50, blank=True, default='English')
	skill_category = models.ForeignKey(LearningInterest, on_delete=models.SET_NULL, null=True, blank=True, related_name='courses')
	# Premium courses are filed under their own list — see `PremiumCategory`. A
	# course uses one or the other, never both; `clean()` and the serializer
	# null the wrong one rather than letting a course sit in two taxonomies.
	premium_category = models.ForeignKey(PremiumCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='courses')
	subject = models.ForeignKey(Subject, on_delete=models.PROTECT, null=True, blank=True, related_name='courses')
	grade = models.ForeignKey(Grade, on_delete=models.PROTECT, null=True, blank=True, related_name='courses')
	is_paid = models.BooleanField(default=False)
	price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
	thumbnail_url = models.URLField(blank=True)
	is_published = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'courses'

	def clean(self):
		"""Rules the columns cannot express.

		**A premium course must be paid.** The product has no free premium course,
		so `is_paid=False` on one is not a cheaper premium course, it is a
		contradiction — and it would hand the course out for nothing while the
		catalogue still labelled it premium.

		**Its price is required to publish, not to save.** The builder creates the
		row at step 1 and asks for the amount at step 3, so a draft that is already
		marked paid has no price yet; demanding one here would make the draft
		unsaveable from the admin too.

		This is the admin/form path; `CourseSerializer.validate` carries the same
		rules for the API, which writes rows without calling `full_clean`.
		"""
		from django.core.exceptions import ValidationError
		if self.course_type == 'premium':
			if not self.is_paid:
				raise ValidationError({'is_paid': 'A premium course must be paid.'})
			if self.is_published and (self.price is None or self.price <= 0):
				raise ValidationError({'price': 'A published premium course must have a price.'})
			if self.skill_category_id:
				raise ValidationError({
					'skill_category': 'A premium course uses the premium categories, not the skill ones.'
				})
		elif self.premium_category_id:
			raise ValidationError({
				'premium_category': 'Only a premium course may use a premium category.'
			})

	def __str__(self):
		return self.title


class Topic(models.Model):
	chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name='topics')
	name = models.CharField(max_length=200)
	order = models.PositiveSmallIntegerField(default=0)

	class Meta:
		db_table = 'topics'
		ordering = ['order']

	def __str__(self):
		return self.name


class Lesson(models.Model):
	CONTENT_TYPE_CHOICES = (
		('video', 'Video'),
		('pdf', 'PDF'),
		('ebook', 'Ebook'),
		('text', 'Text'),
	)

	topic = models.ForeignKey(Topic, on_delete=models.CASCADE, null=True, blank=True, related_name='lessons')
	course = models.ForeignKey(Course, on_delete=models.CASCADE, null=True, blank=True, related_name='lessons')

	title = models.CharField(max_length=200)
	section = models.CharField(max_length=200, null=True, blank=True)
	day_number = models.PositiveSmallIntegerField(null=True, blank=True)
	duration_seconds = models.PositiveIntegerField(null=True, blank=True)
	is_preview = models.BooleanField(default=False)
	content_type = models.CharField(max_length=10, choices=CONTENT_TYPE_CHOICES)
	content_url = models.URLField(blank=True)
	content_text = models.TextField(blank=True)
	order = models.PositiveSmallIntegerField(default=0)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'lessons'
		ordering = ['order']

	def __str__(self):
		return self.title


class InstructorSignupOTP(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='instructor_signup_otps')
	otp_hash = models.CharField(max_length=128)
	created_at = models.DateTimeField(auto_now_add=True)
	expires_at = models.DateTimeField()
	is_used = models.BooleanField(default=False)
	failed_attempts = models.PositiveSmallIntegerField(default=0)

	class Meta:
		db_table = 'instructor_signup_otps'
		ordering = ['-created_at', '-pk']


class PasswordResetOTP(models.Model):
	user = models.ForeignKey(
		User,
		on_delete=models.CASCADE,
		related_name='password_reset_otps'
	)

	otp_hash = models.CharField(max_length=128)
	created_at = models.DateTimeField(auto_now_add=True)
	expires_at = models.DateTimeField()
	is_used = models.BooleanField(default=False)
	failed_attempts = models.PositiveSmallIntegerField(default=0)

	class Meta:
		db_table = 'password_reset_otps'
		ordering = ['-created_at']

	def __str__(self):
		return f'Password reset OTP for {self.user.email}'


class Enrollment(models.Model):
	STATUS_CHOICES = (
		('pending_payment', 'Pending payment'),
		('active', 'Active'),
		('completed', 'Completed'),
		('cancelled', 'Cancelled'),
	)

	# Where the student came from, sent by the app on enroll. Rows from before
	# this field existed are `unknown`; nothing guesses a split for them.
	SOURCE_CHOICES = (
		('direct', 'Direct & Newsletter'),
		('organic', 'Organic Search / SEO'),
		('social', 'Social & Referrals'),
		('unknown', 'Unknown'),
	)

	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enrollments')
	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
	source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='unknown')
	amount_paid = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
	payment_reference = models.CharField(max_length=200, blank=True)
	enrolled_at = models.DateTimeField(auto_now_add=True)
	completed_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		db_table = 'enrollments'
		constraints = [
			models.UniqueConstraint(fields=['student', 'course'], name='unique_enrollment_per_student_course'),
		]

	def __str__(self):
		return f'{self.student.name} - {self.course.title}'


class CourseReview(models.Model):
	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='course_reviews')
	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='reviews')
	rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
	review = models.TextField(blank=True, default='')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'course_reviews'
		ordering = ['-created_at', '-pk']
		constraints = [
			models.UniqueConstraint(fields=['student', 'course'], name='unique_review_per_student_course'),
			models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name='course_review_rating_1_to_5'),
		]


class LessonProgress(models.Model):
	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lesson_progress')
	lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='progress_records')
	enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, null=True, blank=True, related_name='lesson_progress')
	is_completed = models.BooleanField(default=False)
	completed_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		db_table = 'lesson_progress'
		constraints = [
			models.UniqueConstraint(fields=['student', 'lesson'], name='unique_progress_per_student_lesson'),
		]

	def __str__(self):
		return f'{self.student.name} - {self.lesson.title}'


class LessonWatchTime(models.Model):
	"""Seconds a student watched a lesson, one row per student, lesson and day.

	The player reports small increments; the server adds them and caps each
	one by wall-clock time since the student's previous report, so a client
	cannot claim more time than has passed. Daily rows let the instructor
	analytics sum any date window.
	"""

	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='lesson_watch_time')
	lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='watch_time')
	date = models.DateField()
	watched_seconds = models.PositiveIntegerField(default=0)
	position_seconds = models.PositiveIntegerField(default=0)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'lesson_watch_time'
		constraints = [
			models.UniqueConstraint(fields=['student', 'lesson', 'date'], name='unique_watch_time_per_student_lesson_day'),
		]


class Payment(models.Model):
	PROVIDER_CHOICES = (
		('esewa', 'eSewa'),
		('khalti', 'Khalti'),
	)

	STATUS_CHOICES = (
		('initiated', 'Initiated'),
		('successful', 'Successful'),
		('failed', 'Failed'),
		('cancelled', 'Cancelled'),
	)

	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='payments')
	enrollment = models.ForeignKey(Enrollment, on_delete=models.CASCADE, related_name='payments')
	amount = models.DecimalField(max_digits=8, decimal_places=2)
	provider = models.CharField(max_length=10, choices=PROVIDER_CHOICES)
	transaction_reference = models.CharField(max_length=200, unique=True)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='initiated')
	created_at = models.DateTimeField(auto_now_add=True)
	verified_at = models.DateTimeField(null=True, blank=True)
	# Khalti pidx; eSewa uses transaction_reference as its transaction_uuid.
	gateway_token = models.CharField(max_length=100, blank=True)
	# Khalti transaction_id / eSewa ref_id, once the gateway confirms.
	gateway_transaction_id = models.CharField(max_length=100, blank=True)
	gateway_response = models.JSONField(default=dict, blank=True)

	class Meta:
		db_table = 'payments'

	def __str__(self):
		return f'{self.student.name} - {self.course.title} - {self.status}'


class LearningStreak(models.Model):
	student = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True, related_name='learning_streak')
	current_streak = models.PositiveIntegerField(default=0)
	longest_streak = models.PositiveIntegerField(default=0)
	last_active_date = models.DateField(null=True, blank=True)

	class Meta:
		db_table = 'learning_streaks'

	def __str__(self):
		return f'{self.student.name} - {self.current_streak} day streak'


class StreakHistory(models.Model):
	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='streak_history')
	date = models.DateField()

	class Meta:
		db_table = 'streak_history'
		constraints = [
			models.UniqueConstraint(fields=['student', 'date'], name='unique_streak_day_per_student'),
		]
		ordering = ['-date']

	def __str__(self):
		return f'{self.student.name} - {self.date}'


class StreakSettings(models.Model):
	grace_period_days = models.PositiveIntegerField(default=0)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'streak_settings'

	def __str__(self):
		return f'Streak settings (grace period: {self.grace_period_days} days)'

	@classmethod
	def get_solo(cls):
		obj, _ = cls.objects.get_or_create(pk=1)
		return obj


class Quiz(models.Model):
	course = models.ForeignKey(
		Course,
		on_delete=models.CASCADE,
		related_name='quizzes'
	)
	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	pass_percentage = models.PositiveSmallIntegerField(default=40)
	max_attempts = models.PositiveSmallIntegerField(default=1)
	# One clock for the whole attempt. The next question does not start it again.
	time_limit_seconds = models.PositiveSmallIntegerField(default=180)
	# The module this quiz ends: the same text as `Lesson.section`. Null is a
	# course-level quiz (old rows) or the lessons that have no section.
	section = models.CharField(max_length=200, null=True, blank=True)
	is_published = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'quizzes'
		constraints = [
			models.UniqueConstraint(
				fields=['course', 'section'],
				condition=models.Q(section__isnull=False),
				name='unique_quiz_section_per_course',
			),
		]

	def __str__(self):
		return self.title


class Question(models.Model):
	quiz = models.ForeignKey(
		Quiz,
		on_delete=models.CASCADE,
		related_name='questions'
	)
	text = models.TextField()
	marks = models.PositiveSmallIntegerField(default=1)
	points = models.PositiveIntegerField(default=0)
	order = models.PositiveSmallIntegerField(default=0)
	# Shown before answering; the explanation only after the answer is checked.
	hint = models.TextField(blank=True)
	explanation = models.TextField(blank=True)

	class Meta:
		db_table = 'questions'
		ordering = ['order']

	def __str__(self):
		return self.text


class QuestionOption(models.Model):
	question = models.ForeignKey(
		Question,
		on_delete=models.CASCADE,
		related_name='options'
	)
	text = models.CharField(max_length=500)
	is_correct = models.BooleanField(default=False)

	class Meta:
		db_table = 'question_options'

	def __str__(self):
		return self.text


class QuizAttempt(models.Model):
	student = models.ForeignKey(
		User,
		on_delete=models.CASCADE,
		related_name='quiz_attempts'
	)
	quiz = models.ForeignKey(
		Quiz,
		on_delete=models.CASCADE,
		related_name='attempts'
	)
	enrollment = models.ForeignKey(
		Enrollment,
		on_delete=models.CASCADE,
		null=True,
		blank=True,
		related_name='quiz_attempts'
	)
	score = models.DecimalField(
		max_digits=8,
		decimal_places=2,
		default=0
	)
	percentage = models.DecimalField(
		max_digits=5,
		decimal_places=2,
		default=0
	)
	is_passed = models.BooleanField(default=False)
	started_at = models.DateTimeField(auto_now_add=True)
	completed_at = models.DateTimeField(null=True, blank=True)

	class Meta:
		db_table = 'quiz_attempts'

	def __str__(self):
		return f'{self.student.name} - {self.quiz.title}'


class StudentAnswer(models.Model):
	attempt = models.ForeignKey(
		QuizAttempt,
		on_delete=models.CASCADE,
		related_name='answers'
	)
	question = models.ForeignKey(
		Question,
		on_delete=models.CASCADE,
		related_name='student_answers'
	)
	selected_option = models.ForeignKey(
		QuestionOption,
		on_delete=models.PROTECT,
		related_name='student_answers'
	)
	is_correct = models.BooleanField(default=False)
	marks_awarded = models.DecimalField(
		max_digits=8,
		decimal_places=2,
		default=0
	)

	class Meta:
		db_table = 'student_answers'
		constraints = [
			models.UniqueConstraint(
				fields=['attempt', 'question'],
				name='unique_answer_per_attempt_question'
			)
		]

	def __str__(self):
		return f'{self.attempt_id} - {self.question_id}'


class PointTransaction(models.Model):
	EVENT_TYPES = [
		('quiz_correct_answer', 'Quiz Correct Answer'),
		('quiz_first_time_correct', 'Quiz First-Time Correct'),
		('quiz_completion', 'Quiz Completion'),
		('course_completion', 'Course Completion'),
		('challenge_completion', 'Challenge Completion'),
		('manual_adjustment', 'Manual Adjustment'),
		('reward_redemption', 'Reward Redemption'),
	]

	student = models.ForeignKey(
		User,
		on_delete=models.CASCADE,
		related_name='point_transactions'
	)
	points = models.IntegerField()
	event_type = models.CharField(
		max_length=50,
		choices=EVENT_TYPES
	)

	quiz_attempt = models.ForeignKey(
		QuizAttempt,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='point_transactions'
	)

	question = models.ForeignKey(
		Question,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='point_transactions'
	)

	description = models.CharField(
		max_length=255,
		blank=True
	)

	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'point_transactions'
		ordering = ['-created_at']
		constraints = [
			models.UniqueConstraint(
				fields=[
					'student',
					'event_type',
					'quiz_attempt',
					'question'
				],
				name='unique_point_event_per_question_attempt'
			)
		]

	def __str__(self):
		return (
			f"{self.student.email} - "
			f"{self.points} points - "
			f"{self.event_type}"
		)


class CertificateCriteria(models.Model):
	skill_course_requires_quiz_pass = models.BooleanField(default=True)
	academic_grade_min_completion_percentage = models.PositiveSmallIntegerField(default=80)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'certificate_criteria'

	def __str__(self):
		return 'Certificate criteria'

	@classmethod
	def get_solo(cls):
		obj, _ = cls.objects.get_or_create(pk=1)
		return obj


class Certificate(models.Model):
	CERTIFICATE_TYPE_CHOICES = (
		('course', 'Course Completion'),
		('grade', 'Grade Completion'),
	)

	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='certificates')
	certificate_type = models.CharField(max_length=10, choices=CERTIFICATE_TYPE_CHOICES)
	course = models.ForeignKey(Course, on_delete=models.CASCADE, null=True, blank=True, related_name='certificates')
	grade = models.ForeignKey(Grade, on_delete=models.CASCADE, null=True, blank=True, related_name='certificates')
	issued_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'certificates'
		constraints = [
			models.UniqueConstraint(fields=['student', 'course'], name='unique_course_certificate_per_student'),
			models.UniqueConstraint(fields=['student', 'grade'], name='unique_grade_certificate_per_student'),
		]

	def __str__(self):
		target = self.course.title if self.course else (self.grade.name if self.grade else '')
		return f'{self.student.name} - {target}'


class Badge(models.Model):
	CRITERIA_TYPE_CHOICES = (
		('quiz_perfect_score', 'Perfect Quiz Score'),
		('streak_milestone', 'Streak Milestone'),
		('course_completion_count', 'Number of Courses Completed'),
	)

	name = models.CharField(max_length=150, unique=True)
	description = models.TextField(blank=True)
	icon_url = models.URLField(blank=True)
	criteria_type = models.CharField(max_length=30, choices=CRITERIA_TYPE_CHOICES)
	criteria_value = models.PositiveIntegerField(help_text='e.g. streak days needed, or number of courses')
	is_active = models.BooleanField(default=True)

	class Meta:
		db_table = 'badges'

	def __str__(self):
		return self.name


class StudentBadge(models.Model):
	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='badges')
	badge = models.ForeignKey(Badge, on_delete=models.CASCADE, related_name='awarded_to')
	awarded_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'student_badges'
		constraints = [
			models.UniqueConstraint(fields=['student', 'badge'], name='unique_badge_per_student'),
		]

	def __str__(self):
		return f'{self.student.name} - {self.badge.name}'


class AdminAuditLog(models.Model):
	ACTION_CHOICES = (
		('user_updated', 'User details updated'),
		('user_deactivated', 'User deactivated'),
		('user_reactivated', 'User reactivated'),
		('verification_approved', 'Verification approved'),
		('verification_rejected', 'Verification rejected'),
	)

	admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='admin_actions')
	action = models.CharField(max_length=40, choices=ACTION_CHOICES)
	target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_entries')
	details = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'admin_audit_logs'
		ordering = ['-created_at']

	def __str__(self):
		return f'{self.get_action_display()} - {self.created_at:%Y-%m-%d %H:%M}'


class Challenge(models.Model):
	title = models.CharField(max_length=200)
	description = models.TextField()
	subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name='challenges')
	grade = models.ForeignKey(Grade, on_delete=models.SET_NULL, null=True, blank=True, related_name='challenges')
	points = models.PositiveIntegerField(default=0)
	end_at = models.DateTimeField()
	created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_challenges')
	is_published = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'challenges'
		ordering = ['-created_at']

	def __str__(self):
		return self.title


class ChallengeParticipant(models.Model):
	STATUS_CHOICES = (
		('joined', 'Joined'),
		('submitted', 'Submitted'),
		('approved', 'Approved'),
		('rejected', 'Rejected'),
	)

	challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, related_name='participants')
	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='challenge_participations')
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='joined')
	submission_text = models.TextField(blank=True)
	submission_url = models.URLField(max_length=500, blank=True)
	submitted_at = models.DateTimeField(null=True, blank=True)
	reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_challenge_submissions')
	reviewed_at = models.DateTimeField(null=True, blank=True)
	points_awarded = models.PositiveIntegerField(default=0)
	is_winner = models.BooleanField(default=False)
	joined_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'challenge_participants'
		ordering = ['-joined_at']
		constraints = [
			models.UniqueConstraint(fields=['challenge', 'student'], name='unique_participant_per_challenge'),
		]

	def __str__(self):
		return f'{self.student.name} - {self.challenge.title}'


class Short(models.Model):
	title = models.CharField(max_length=200)

	instructor = models.ForeignKey(
		User,
		on_delete=models.PROTECT,
		related_name='shorts'
	)

	video_url = models.URLField()

	thumbnail_url = models.URLField(
		blank=True
	)

	# The text under the video. Hashtags stay inline here; search covers them,
	# so there is no separate tag table until a screen needs one.
	caption = models.TextField(blank=True, default='')
	# Same taxonomy students pick at onboarding, which is what the "For you"
	# and STEM feeds filter on.
	topic = models.ForeignKey(LearningInterest, on_delete=models.SET_NULL, null=True, blank=True, related_name='shorts')
	# Optional links behind the course chip, the Quiz button and the Challenge
	# feed. SET_NULL: deleting a course or quiz must not delete the video.
	course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name='shorts')
	quiz = models.ForeignKey(Quiz, on_delete=models.SET_NULL, null=True, blank=True, related_name='shorts')
	challenge = models.ForeignKey(Challenge, on_delete=models.SET_NULL, null=True, blank=True, related_name='shorts')

	is_published = models.BooleanField(
		default=False
	)

	view_count = models.PositiveIntegerField(
		default=0
	)

	created_at = models.DateTimeField(
		auto_now_add=True
	)

	updated_at = models.DateTimeField(
		auto_now=True
	)

	class Meta:
		db_table = 'shorts'
		ordering = ['-created_at']

	def __str__(self):
		return self.title


class ShortView(models.Model):
	student = models.ForeignKey(
		User,
		on_delete=models.CASCADE,
		related_name='short_views'
	)

	short = models.ForeignKey(
		Short,
		on_delete=models.CASCADE,
		related_name='views'
	)

	viewed_at = models.DateTimeField(
		auto_now_add=True
	)

	class Meta:
		db_table = 'short_views'
		constraints = [
			models.UniqueConstraint(
				fields=['student', 'short'],
				name='unique_short_view_per_student'
			)
		]

	def __str__(self):
		return f'{self.student.email} - {self.short.title}'


class ShortLike(models.Model):
	student = models.ForeignKey(
		User,
		on_delete=models.CASCADE,
		related_name='short_likes'
	)

	short = models.ForeignKey(
		Short,
		on_delete=models.CASCADE,
		related_name='likes'
	)

	created_at = models.DateTimeField(
		auto_now_add=True
	)

	class Meta:
		db_table = 'short_likes'
		constraints = [
			models.UniqueConstraint(
				fields=['student', 'short'],
				name='unique_short_like_per_student'
			)
		]

	def __str__(self):
		return f'{self.student.email} likes {self.short.title}'


class ShortBookmark(models.Model):
	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='short_bookmarks')
	short = models.ForeignKey(Short, on_delete=models.CASCADE, related_name='bookmarks')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'short_bookmarks'
		constraints = [models.UniqueConstraint(
			fields=['student', 'short'], name='unique_short_bookmark_per_student',
		)]


class ShortComment(models.Model):
	student = models.ForeignKey(
		User,
		on_delete=models.CASCADE,
		related_name='short_comments'
	)

	short = models.ForeignKey(
		Short,
		on_delete=models.CASCADE,
		related_name='comments'
	)

	# Set on a reply. Threads are one level deep: a reply to a reply is stored
	# under the same top-level comment, so this never points at a reply.
	parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='replies')

	text = models.TextField()

	created_at = models.DateTimeField(
		auto_now_add=True
	)

	class Meta:
		db_table = 'short_comments'
		ordering = ['-created_at']

	def __str__(self):
		return f'{self.student.email} - {self.short.title}'


class ShortCommentLike(models.Model):
	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='short_comment_likes')
	comment = models.ForeignKey(ShortComment, on_delete=models.CASCADE, related_name='likes')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'short_comment_likes'
		constraints = [models.UniqueConstraint(
			fields=['student', 'comment'], name='unique_short_comment_like_per_user',
		)]


class EBook(models.Model):
	DIFFICULTY_CHOICES = [('beginner', 'Beginner'), ('intermediate', 'Intermediate'), ('advanced', 'Advanced')]
	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	author = models.CharField(max_length=200, blank=True)
	subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True, related_name='ebooks')
	grade = models.ForeignKey(Grade, on_delete=models.SET_NULL, null=True, blank=True, related_name='ebooks')
	uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='ebooks')
	cover_url = models.URLField(blank=True)
	file_url = models.URLField(blank=True)
	category = models.CharField(max_length=100, blank=True)
	difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, blank=True)
	highlights = models.JSONField(default=list, blank=True, validators=[validate_highlights])
	# NULL is unknown/unreviewed legacy pricing, never an implicit free grant.
	price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
	currency = models.CharField(max_length=3, choices=[('NPR', 'NPR')], default='NPR')
	cover_image = models.ImageField(upload_to=book_cover_path, blank=True, validators=[validate_book_cover])
	source_file = models.FileField(storage=PrivateBookStorage(), upload_to=book_source_path, blank=True, validators=[validate_book_source])
	file_format = models.CharField(max_length=4, choices=[('pdf', 'PDF'), ('epub', 'EPUB')], blank=True, editable=False)
	is_published = models.BooleanField(default=False)
	published_at = models.DateTimeField(null=True, blank=True, editable=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'ebooks'
		ordering = ['-created_at']
		constraints = [
			models.CheckConstraint(condition=models.Q(price__isnull=True) | models.Q(price__gte=0), name='ebook_price_nonnegative'),
			models.CheckConstraint(condition=models.Q(currency='NPR'), name='ebook_currency_npr'),
		]

	def clean(self):
		super().clean()
		from django.core.exceptions import ValidationError
		try:
			validate_highlights(self.highlights)
		except ValidationError as exc:
			raise ValidationError({'highlights': exc.messages})
		if self.is_published and not self.source_file and not self.file_url:
			raise ValidationError({'source_file': 'Upload a PDF/EPUB or provide a legacy file URL.'})

	def save(self, *args, **kwargs):
		from django.utils import timezone
		from pathlib import Path
		if self.source_file:
			self.file_format = Path(self.source_file.name).suffix.lower().lstrip('.')
		if self.is_published and self.published_at is None:
			self.published_at = timezone.now()
		elif not self.is_published:
			self.published_at = None
		if kwargs.get('update_fields') is not None:
			kwargs['update_fields'] = set(kwargs['update_fields']) | {'file_format', 'published_at'}
		super().save(*args, **kwargs)

	def __str__(self):
		return self.title


class BookChapter(models.Model):
	book = models.ForeignKey(EBook, on_delete=models.CASCADE, related_name='chapters')
	chapter_number = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(10000)])
	title = models.CharField(max_length=200)
	content = models.TextField(blank=True, max_length=200000)
	# Import identity, never a public asset URL; excluded from reader responses.
	source_reference = models.CharField(max_length=500, null=True, blank=True, default=None)
	imported_digest = models.CharField(max_length=64, blank=True, editable=False)
	estimated_reading_minutes = models.PositiveIntegerField(default=0, editable=False)
	pdf_page_start = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
	pdf_page_end = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'book_chapters'
		ordering = ['chapter_number', 'pk']
		constraints = [
			models.UniqueConstraint(fields=['book', 'chapter_number'], name='unique_book_chapter_number'),
			models.UniqueConstraint(fields=['book', 'source_reference'], name='unique_book_import_reference'),
			models.CheckConstraint(condition=models.Q(chapter_number__gte=1), name='book_chapter_positive_number'),
			models.CheckConstraint(condition=(models.Q(pdf_page_start__isnull=True, pdf_page_end__isnull=True) | models.Q(pdf_page_start__isnull=False, pdf_page_end__isnull=False, pdf_page_start__gte=1, pdf_page_end__gte=models.F('pdf_page_start'))), name='book_chapter_valid_pdf_range'),
		]

	def clean(self):
		from django.core.exceptions import ValidationError
		if bool(self.pdf_page_start) != bool(self.pdf_page_end) or (self.pdf_page_start and self.pdf_page_end < self.pdf_page_start):
			raise ValidationError('Provide a valid inclusive PDF page range.')
		if self.pdf_page_start and self.book.file_format != 'pdf':
			raise ValidationError('Page ranges require a PDF book.')
		if self.pdf_page_start:
			from .book_reader import validate_pdf_range
			validate_pdf_range(self.book, self.pdf_page_start, self.pdf_page_end)

	def save(self, *args, **kwargs):
		from .book_reader import plain_book_text, reading_minutes
		self.content = plain_book_text(self.content)
		self.title = plain_book_text(self.title)
		self.estimated_reading_minutes = reading_minutes(self.content)
		if kwargs.get('update_fields') is not None:
			kwargs['update_fields'] = set(kwargs['update_fields']) | {'content', 'title', 'estimated_reading_minutes', 'updated_at'}
		super().save(*args, **kwargs)


	def delete(self, *args, **kwargs):
		from django.db import transaction
		with transaction.atomic():
			EBook.objects.select_for_update().get(pk=self.book_id)
			BookReadingProgress.objects.filter(last_chapter=self).update(last_chapter=None, position={})
			return super().delete(*args, **kwargs)


class BookReadingProgress(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='book_reading_progress')
	book = models.ForeignKey(EBook, on_delete=models.CASCADE, related_name='reading_progress')
	last_chapter = models.ForeignKey(BookChapter, on_delete=models.SET_NULL, null=True, blank=True)
	position = models.JSONField(default=dict, blank=True)
	last_read_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'book_reading_progress'
		constraints = [models.UniqueConstraint(fields=['user', 'book'], name='unique_user_book_progress')]


class BookChapterCompletion(models.Model):
	progress = models.ForeignKey(BookReadingProgress, on_delete=models.CASCADE, related_name='completions')
	chapter = models.ForeignKey(BookChapter, on_delete=models.CASCADE, related_name='completions')
	completed_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'book_chapter_completions'
		constraints = [models.UniqueConstraint(fields=['progress', 'chapter'], name='unique_book_chapter_completion')]


class BookBookmark(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='book_bookmarks')
	book = models.ForeignKey(EBook, on_delete=models.CASCADE, related_name='bookmarks')
	chapter = models.ForeignKey(BookChapter, on_delete=models.CASCADE, related_name='bookmarks')
	position = models.JSONField(default=dict, blank=True)
	anchor = models.CharField(max_length=120, blank=True)
	note = models.TextField(blank=True, max_length=2000)
	locator_key = models.CharField(max_length=64, editable=False)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'book_bookmarks'
		ordering = ['-created_at', '-pk']
		constraints = [models.UniqueConstraint(fields=['user', 'chapter', 'locator_key'], name='unique_user_chapter_bookmark')]


class ReaderSettings(models.Model):
	user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='reader_settings')
	font_family = models.CharField(max_length=20, choices=[('system', 'System'), ('serif', 'Serif'), ('sans-serif', 'Sans serif'), ('monospace', 'Monospace')], default='system')
	font_size = models.PositiveSmallIntegerField(default=18, validators=[MinValueValidator(12), MaxValueValidator(32)])
	line_spacing = models.DecimalField(max_digits=2, decimal_places=1, default='1.5', validators=[MinValueValidator(1), MaxValueValidator(2.5)])
	theme = models.CharField(max_length=5, choices=[('light', 'Light'), ('sepia', 'Sepia'), ('dark', 'Dark')], default='light')

	class Meta:
		db_table = 'reader_settings'
		constraints = [
			models.CheckConstraint(condition=models.Q(font_size__gte=12, font_size__lte=32), name='reader_font_size_range'),
			models.CheckConstraint(condition=models.Q(line_spacing__gte=1, line_spacing__lte=2.5), name='reader_spacing_range'),
		]


class Notification(models.Model):
	TYPE_COURSE_UPDATE = 'course_update'
	TYPE_ASSESSMENT_RESULT = 'assessment_result'
	TYPE_PAYMENT = 'payment'
	TYPE_CERTIFICATE = 'certificate'
	TYPE_CHALLENGE = 'challenge'
	TYPE_SYSTEM = 'system'

	TYPE_CHOICES = [
		(TYPE_COURSE_UPDATE, 'Course Update'),
		(TYPE_ASSESSMENT_RESULT, 'Assessment Result'),
		(TYPE_PAYMENT, 'Payment Confirmation'),
		(TYPE_CERTIFICATE, 'Certificate'),
		(TYPE_CHALLENGE, 'Challenge'),
		(TYPE_SYSTEM, 'System'),
	]

	recipient = models.ForeignKey(
		User,
		on_delete=models.CASCADE,
		related_name='notifications'
	)

	notification_type = models.CharField(
		max_length=30,
		choices=TYPE_CHOICES,
		default=TYPE_SYSTEM
	)

	title = models.CharField(
		max_length=255
	)

	message = models.TextField()

	related_type = models.CharField(
		max_length=50,
		blank=True
	)

	related_id = models.PositiveBigIntegerField(
		null=True,
		blank=True
	)

	is_read = models.BooleanField(
		default=False
	)

	read_at = models.DateTimeField(
		null=True,
		blank=True
	)

	created_at = models.DateTimeField(
		auto_now_add=True
	)

	class Meta:
		db_table = 'notifications'
		ordering = ['-created_at']
		indexes = [
			models.Index(
				fields=['recipient', 'is_read']
			),
			models.Index(
				fields=['recipient', '-created_at']
			),
		]

	def __str__(self):
		return f'{self.recipient.email} - {self.title}'


class AIActivity(models.Model):
	ACTIVITY_TYPE_CHOICES = (
		('practice_questions', 'Practice Questions'),
		('crossword', 'Crossword'),
		('challenge', 'Challenge'),
	)

	STATUS_CHOICES = (
		('pending_review', 'Pending Review'),
		('approved', 'Approved'),
		('rejected', 'Rejected'),
	)

	generated_by = models.ForeignKey(
		User,
		on_delete=models.CASCADE,
		related_name='generated_ai_activities'
	)
	activity_type = models.CharField(
		max_length=30,
		choices=ACTIVITY_TYPE_CHOICES
	)
	topic = models.CharField(max_length=255)
	learning_context = models.TextField(blank=True)
	difficulty = models.CharField(max_length=20, default='medium')
	generated_content = models.JSONField()
	status = models.CharField(
		max_length=20,
		choices=STATUS_CHOICES,
		default='pending_review'
	)
	reviewed_by = models.ForeignKey(
		User,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='reviewed_ai_activities'
	)
	review_notes = models.TextField(blank=True)
	reviewed_at = models.DateTimeField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'ai_activities'
		ordering = ['-created_at']

	def __str__(self):
		return (
			f'{self.activity_type} - '
			f'{self.topic} - '
			f'{self.status}'
		)


class LocalAuthorityProfile(models.Model):
	user = models.OneToOneField(
		User,
		on_delete=models.CASCADE,
		related_name='local_authority_profile'
	)

	municipality = models.ForeignKey(
		Municipality,
		on_delete=models.PROTECT,
		related_name='local_authority_profiles'
	)

	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'local_authority_profiles'

	def __str__(self):
		return f'{self.user.email} - {self.municipality.name}'


class AuditLog(models.Model):
	ACTION_CHOICES = (
		('create', 'Create'),
		('update', 'Update'),
		('delete', 'Delete'),
		('activate', 'Activate'),
		('deactivate', 'Deactivate'),
		('role_change', 'Role Change'),
		('verification_change', 'Verification Change'),
		('permission_change', 'Permission Change'),
	)

	actor = models.ForeignKey(
		User,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='audit_actions'
	)

	action = models.CharField(
		max_length=40,
		choices=ACTION_CHOICES
	)

	target_type = models.CharField(
		max_length=100
	)

	target_id = models.PositiveBigIntegerField(
		null=True,
		blank=True
	)

	target_display = models.CharField(
		max_length=255,
		blank=True
	)

	description = models.TextField(
		blank=True
	)

	metadata = models.JSONField(
		default=dict,
		blank=True
	)

	ip_address = models.GenericIPAddressField(
		null=True,
		blank=True
	)

	created_at = models.DateTimeField(
		auto_now_add=True
	)

	class Meta:
		db_table = 'audit_logs'
		ordering = ['-created_at']

	def __str__(self):
		actor = self.actor.email if self.actor else 'System'
		return f'{actor} - {self.action} - {self.target_type}'


# =========================================================
# Rewards & Redemption
# =========================================================


class Reward(models.Model):
        name = models.CharField(max_length=150)
        description = models.TextField(blank=True)
        points_required = models.PositiveIntegerField()

        stock = models.PositiveIntegerField(
                null=True,
                blank=True,
                help_text='Leave empty for unlimited stock.'
        )

        is_active = models.BooleanField(default=True)

        created_at = models.DateTimeField(auto_now_add=True)
        updated_at = models.DateTimeField(auto_now=True)

        class Meta:
                db_table = 'rewards'
                ordering = ['points_required', 'name']

        def __str__(self):
                return f'{self.name} - {self.points_required} points'


class Redemption(models.Model):
        STATUS_CHOICES = [
                ('pending', 'Pending'),
                ('approved', 'Approved'),
                ('fulfilled', 'Fulfilled'),
                ('rejected', 'Rejected'),
                ('cancelled', 'Cancelled'),
        ]

        student = models.ForeignKey(
                User,
                on_delete=models.CASCADE,
                related_name='redemptions'
        )

        reward = models.ForeignKey(
                Reward,
                on_delete=models.PROTECT,
                related_name='redemptions'
        )

        points_spent = models.PositiveIntegerField()

        status = models.CharField(
                max_length=20,
                choices=STATUS_CHOICES,
                default='pending'
        )

        point_transaction = models.OneToOneField(
                PointTransaction,
                on_delete=models.PROTECT,
                related_name='redemption'
        )

        note = models.TextField(blank=True)

        created_at = models.DateTimeField(auto_now_add=True)
        updated_at = models.DateTimeField(auto_now=True)

        class Meta:
                db_table = 'redemptions'
                ordering = ['-created_at']

        def __str__(self):
                return (
                        f'{self.student.email} - '
                        f'{self.reward.name} - '
                        f'{self.status}'
                )



def event_image_path(instance, filename):
	from pathlib import Path
	from uuid import uuid4
	return f'events/{uuid4().hex}{Path(filename).suffix.lower()}'


class Event(models.Model):
	FORMAT_CHOICES = (
		('in_person', 'In person'),
		('online', 'Online'),
		('hybrid', 'Hybrid'),
	)

	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	highlights = models.JSONField(default=list, blank=True)
	cover_image = models.ImageField(upload_to=event_image_path, blank=True)

	host = models.ForeignKey(
		User,
		on_delete=models.SET_NULL,
		null=True,
		blank=True,
		related_name='hosted_events',
	)
	host_role = models.CharField(max_length=150, blank=True)

	start_at = models.DateTimeField()
	end_at = models.DateTimeField()
	format = models.CharField(max_length=20, choices=FORMAT_CHOICES, default='in_person')

	venue_name = models.CharField(max_length=200, blank=True)
	city = models.CharField(max_length=150, blank=True)
	province = models.ForeignKey(Province, on_delete=models.PROTECT, null=True, blank=True, related_name='events')
	district = models.ForeignKey(District, on_delete=models.PROTECT, null=True, blank=True, related_name='events')
	municipality = models.ForeignKey(Municipality, on_delete=models.PROTECT, null=True, blank=True, related_name='events')
	latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
	longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

	capacity = models.PositiveIntegerField(null=True, blank=True)
	is_published = models.BooleanField(default=False)

	created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_events')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'events'
		ordering = ['start_at', 'id']
		indexes = [models.Index(fields=['is_published', 'end_at'])]
		constraints = [models.CheckConstraint(
			condition=models.Q(end_at__gte=models.F('start_at')),
			name='event_valid_schedule',
		)]

	def __str__(self):
		return self.title


class EventRegistration(models.Model):
	STATUS_CHOICES = (
		('registered', 'Registered'),
		('waitlisted', 'Waitlisted'),
	)

	event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='registrations')
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_registrations')
	status = models.CharField(max_length=20, choices=STATUS_CHOICES)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'event_registrations'
		ordering = ['created_at', 'id']
		constraints = [models.UniqueConstraint(fields=['event', 'user'], name='unique_event_registration')]


class EventBookmark(models.Model):
	event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='bookmarks')
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='event_bookmarks')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = 'event_bookmarks'
		ordering = ['-created_at', '-id']
		constraints = [models.UniqueConstraint(fields=['event', 'user'], name='unique_event_bookmark')]


class BootcampProfile(models.Model):
    STATUS_CHOICES = [(v, v.title()) for v in ['upcoming', 'ongoing', 'completed', 'cancelled']]
    course = models.OneToOneField(Course, on_delete=models.CASCADE, related_name='bootcamp_profile')
    venue_name = models.CharField(max_length=150)
    days = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    starts_on = models.DateField()
    ends_on = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='upcoming')
    episode_no = models.PositiveSmallIntegerField(null=True, blank=True)
    short_description = models.CharField(max_length=300, blank=True)
    hero_video_url = models.URLField(blank=True)
    hero_poster_url = models.URLField(blank=True)
    quality_label = models.CharField(max_length=8, blank=True)
    view_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'bootcamp_profiles'
        constraints = [
            models.CheckConstraint(condition=models.Q(days__gte=1), name='bootcamp_positive_days'),
            models.CheckConstraint(condition=models.Q(ends_on__gte=models.F('starts_on')), name='bootcamp_valid_dates'),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.course_id and self.course.course_type != 'bootcamp':
            raise ValidationError({'course': 'Only bootcamp courses may have a bootcamp profile.'})
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({'ends_on': 'End date must not precede start date.'})


class CourseInstructor(models.Model):
    ROLE_CHOICES = [(v, v.title()) for v in ['lead', 'coach', 'guest']]
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='instructors')
    instructor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='course_roster')
    role = models.CharField(max_length=5, choices=ROLE_CHOICES)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'course_instructors'
        ordering = ['order', 'pk']
        constraints = [models.UniqueConstraint(fields=['course', 'instructor'], name='unique_course_instructor')]


class CourseResource(models.Model):
    """One downloadable file attached to a course, usually to one lesson.

    **Any published course, not only a bootcamp.** This started as
    `BootcampResource` and `clean()` refused every other `course_type`, so
    `GET /courses/{id}/resources/` 404'd every course the builder can create.
    The player's Resources tab exists on skill courses too.

    `lesson` is what makes a resource per-lesson: the builder attaches files
    while it is editing a lesson, and the player's tab shows the current
    lesson's files. It is nullable because a bootcamp's pack predates this and
    is course-wide, and because a lesson's `course` is itself nullable (a
    lesson may hang off a `Topic` instead) — so the consistency check below
    only compares when both sides are set.
    """

    FORMAT_CHOICES = [(v, v.upper()) for v in ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'figma', 'svg', 'zip', 'link', 'other']]
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='course_resources')
    lesson = models.ForeignKey('Lesson', on_delete=models.CASCADE, null=True, blank=True, related_name='resources')
    section = models.CharField(max_length=200, blank=True)
    title = models.CharField(max_length=200)
    file_format = models.CharField(max_length=5, choices=FORMAT_CHOICES)
    file_url = models.URLField()
    file_size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'course_resources'
        ordering = ['order', 'pk']

    def clean(self):
        from django.core.exceptions import ValidationError
        # A resource may not point at a lesson belonging to another course —
        # that would publish one course's files under another's tab.
        if self.lesson_id and self.lesson.course_id and self.course_id and self.lesson.course_id != self.course_id:
            raise ValidationError({'lesson': 'That lesson belongs to a different course.'})


class CourseDiscussion(models.Model):
    """One Q&A message on a course's player tab.

    **Any published course, not only a bootcamp.** This started as a bootcamp
    subresource and `clean()` refused every other `course_type`; the player's Q&A
    tab exists on skill and academic courses too, so the restriction only meant
    that endpoint 404'd for every course the builder can create.

    Threads are **one level deep**: a row with `parent` set is a reply, and a
    reply may not itself be answered. That is enforced here and re-checked by
    `DiscussionCreateSerializer` so the API answers 400 instead of 500.
    """

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='course_discussions')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='course_discussions')
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='replies')
    body = models.TextField(max_length=2000)
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'course_discussions'
        ordering = ['-created_at', '-pk']

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parent_id and (self.parent.course_id != self.course_id or self.parent.parent_id):
            raise ValidationError({'parent': 'Replies must reference a top-level discussion in the same course.'})


class DiscussionLike(models.Model):
    discussion = models.ForeignKey(CourseDiscussion, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='course_discussion_likes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'discussion_likes'
        constraints = [models.UniqueConstraint(fields=['discussion', 'user'], name='unique_discussion_like')]

class SearchQuery(models.Model):
    """One search a user ran, kept to rank Trending Searches.

    `normalized` groups spellings ("CSS grid", " css  Grid "). Only searches
    that found something count towards trending, so typos and junk never
    surface on other people's screens.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='search_queries')
    query = models.CharField(max_length=100)
    normalized = models.CharField(max_length=100, db_index=True)
    results_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'search_queries'
        ordering = ['-created_at', '-pk']


class SavedBook(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    book = models.ForeignKey(EBook, on_delete=models.CASCADE, related_name='saves')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'book'], name='unique_saved_book')]


class BookReview(models.Model):
    book = models.ForeignKey(EBook, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField()
    review = models.TextField(max_length=2000, blank=True)
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'book'], name='unique_book_review'),
            models.CheckConstraint(condition=models.Q(rating__range=(1, 5)), name='book_review_rating_range'),
        ]
        indexes = [models.Index(fields=['book', 'is_hidden'])]


class BookOrder(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending'
        PROCESSING = 'processing'
        PAID = 'paid'
        FAILED = 'failed'
        CANCELLED = 'cancelled'
        REFUNDED = 'refunded'

    user = models.ForeignKey(User, on_delete=models.PROTECT)
    book = models.ForeignKey(EBook, on_delete=models.PROTECT, related_name='orders')
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='NPR')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=40, blank=True)
    provider_reference = models.CharField(max_length=128, null=True, blank=True)
    provider_transaction = models.CharField(max_length=128, null=True, blank=True)
    active_slot = models.GeneratedField(
        expression=models.Case(models.When(status__in=['pending', 'processing', 'paid'], then=models.Value(True))),
        output_field=models.BooleanField(),
        db_persist=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError

        snapshot_fields = {'user_id', 'book_id', 'reference', 'original_price', 'amount', 'currency'}
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            names = {'user': 'user_id', 'book': 'book_id'}
            snapshot_fields &= {names.get(field, field) for field in update_fields}
        if self.pk is not None and snapshot_fields:
            original = type(self).objects.filter(pk=self.pk).values(*snapshot_fields).first()
            if original and any(getattr(self, field) != value for field, value in original.items()):
                raise ValidationError('Book order identity and price snapshots are immutable.')
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0, original_price__gt=0, currency='NPR'), name='book_order_valid_amount'),
            models.UniqueConstraint(fields=['user', 'book', 'active_slot'], name='unique_active_book_order'),
            models.UniqueConstraint(fields=['provider', 'provider_reference'], name='unique_book_provider_reference'),
            models.UniqueConstraint(fields=['provider', 'provider_transaction'], name='unique_book_provider_transaction'),
            models.CheckConstraint(
                condition=~models.Q(status__in=['paid', 'refunded']) | (
                    models.Q(paid_at__isnull=False, provider_reference__isnull=False, provider_transaction__isnull=False)
                    & ~models.Q(provider='') & ~models.Q(provider_reference='') & ~models.Q(provider_transaction='')
                ),
                name='book_order_paid_evidence',
            ),
        ]
        indexes = [models.Index(fields=['user', '-created_at'])]


class BookEntitlement(models.Model):
    class Source(models.TextChoices):
        FREE = 'free'
        PURCHASE = 'purchase'

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    book = models.ForeignKey(EBook, on_delete=models.PROTECT, related_name='entitlements')
    order = models.OneToOneField(BookOrder, on_delete=models.PROTECT, null=True, blank=True)
    source = models.CharField(max_length=8, choices=Source.choices)
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'book', 'source'], condition=models.Q(source='free'), name='unique_free_book_entitlement'),
            models.UniqueConstraint(fields=['order'], condition=models.Q(order__isnull=False), name='unique_order_book_entitlement'),
            models.CheckConstraint(condition=models.Q(source='free', order__isnull=True) | models.Q(source='purchase', order__isnull=False), name='book_entitlement_source_order'),
        ]
        indexes = [models.Index(fields=['user', 'revoked_at'])]
