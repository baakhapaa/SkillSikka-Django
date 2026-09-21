from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


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


class StudentProfile(models.Model):
	user = models.OneToOneField(
		User,
		on_delete=models.CASCADE,
		primary_key=True,
		related_name='student_profile'
	)

	grade = models.ForeignKey(
		Grade,
		on_delete=models.PROTECT,
		related_name='student_profiles'
	)

	province = models.ForeignKey(
		Province,
		on_delete=models.PROTECT,
		related_name='student_profiles'
	)

	district = models.ForeignKey(
		District,
		on_delete=models.PROTECT,
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

	qualification = models.CharField(max_length=255)
	subject_expertise = models.TextField()

	experience_years = models.DecimalField(
		max_digits=5,
		decimal_places=2
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


class Course(models.Model):
	COURSE_TYPE_CHOICES = (
		('academic', 'Academic'),
		('skill', 'Skill Development'),
	)

	title = models.CharField(max_length=200)
	description = models.TextField(blank=True)
	instructor = models.ForeignKey(User, on_delete=models.PROTECT, related_name='courses')
	course_type = models.CharField(max_length=10, choices=COURSE_TYPE_CHOICES)
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

	student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enrollments')
	course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
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
	is_published = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		db_table = 'quizzes'

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
    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

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

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        db_table = 'point_transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.student.name} - {self.points} points'

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