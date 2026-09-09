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