import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class Role(models.Model):
	name = models.CharField(max_length=40, unique=True)
	description = models.TextField(blank=True)

	def __str__(self):
		return self.name


class Permission(models.Model):
	name = models.CharField(max_length=80, unique=True)
	description = models.TextField(blank=True)

	def __str__(self):
		return self.name


class RolePermission(models.Model):
	role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='role_permissions')
	permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name='role_permissions')

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['role', 'permission'], name='unique_role_permission'),
		]


class UserManager(BaseUserManager):
	def create_user(self, email, password=None, **extra_fields):
		if not email:
			raise ValueError('An email address is required.')
		user = self.model(email=self.normalize_email(email), **extra_fields)
		if password:
			user.set_password(password)
		else:
			user.set_unusable_password()
		user.save(using=self._db)
		return user

	def create_superuser(self, email, password=None, **extra_fields):
		if 'role' not in extra_fields:
			extra_fields['role'] = Role.objects.get(name='super_admin')
		extra_fields.setdefault('is_staff', True)
		extra_fields.setdefault('is_superuser', True)
		extra_fields.setdefault('onboarding_completed', True)
		extra_fields.setdefault('is_active', True)
		return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
	VERIFICATION_CHOICES = (
		('not_applicable', 'Not applicable'),
		('pending', 'Pending'),
		('verified', 'Verified'),
		('rejected', 'Rejected'),
	)

	id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
	name = models.CharField(max_length=150)
	email = models.EmailField(unique=True)
	phone_country_code = models.CharField(max_length=8, blank=True)
	phone_number = models.CharField(max_length=30, blank=True)
	role = models.ForeignKey(Role, on_delete=models.PROTECT, null=True, blank=True, related_name='users')
	profile_photo_url = models.URLField(blank=True)
	gender = models.CharField(max_length=10, blank=True)
	dob = models.DateField(null=True, blank=True)
	location = models.CharField(max_length=255, blank=True)
	onboarding_completed = models.BooleanField(default=False)
	onboarding_step = models.PositiveSmallIntegerField(default=0)
	verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default='not_applicable')
	verified_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_users')
	verified_at = models.DateTimeField(null=True, blank=True)
	is_active = models.BooleanField(default=True)
	is_staff = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	objects = UserManager()
	USERNAME_FIELD = 'email'
	REQUIRED_FIELDS = ['name']

	def __str__(self):
		return self.name or self.email

	def has_role_permission(self, permission_name):
		if self.is_superuser:
			return True
		return bool(self.role and self.role.role_permissions.filter(permission__name=permission_name).exists())
