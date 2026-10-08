from datetime import timedelta
from collections.abc import Mapping
from pathlib import Path
import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.storage import default_storage
from django.core.mail import send_mail
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.text import slugify
from rest_framework import serializers
from rest_framework_simplejwt.token_blacklist.models import (
	BlacklistedToken,
	OutstandingToken,
)
from .documents import (
	save_upload,
	validate_certificate_files,
	validate_cv_resume_file,
	validate_profile_photo_file,
	validate_student_id_card_file,
)
from .signup_otp import OTP_EXPIRY_SECONDS, OTP_EXPIRY_TEXT, issue_signup_otp
from .student_onboarding import update_student_onboarding

from .models import (
	Badge,
	Certificate,
	CertificateCriteria,
	Challenge,
	ChallengeParticipant,
	Chapter,
	Course,
	CourseReview,
	District,
	Enrollment,
	Grade,
	InstructorProfile,
	LearningStreak,
	Lesson,
	LessonProgress,
	Municipality,
	PasswordResetOTP,
	Payment,
	PointTransaction,
	Reward,
	Redemption,
	Province,
	Question,
	QuestionOption,
	Quiz,
	QuizAttempt,
	School,
	StudentAnswer,
	StudentBadge,
	StudentProfile,
	Subject,
	Topic,
	User,
	VerificationDocument,
	Short,
	ShortComment,
	ShortLike,
	ShortView,
	EBook,
	Notification,
)


class LocationSerializer(serializers.ModelSerializer):
	class Meta:
		fields = ['id', 'name']


class ProvinceSerializer(LocationSerializer):
	class Meta(LocationSerializer.Meta):
		model = Province


class DistrictSerializer(LocationSerializer):
	province_id = serializers.IntegerField(source='province.id', read_only=True)

	class Meta(LocationSerializer.Meta):
		model = District
		fields = ['id', 'name', 'province_id']


class MunicipalitySerializer(LocationSerializer):
	district_id = serializers.IntegerField(source='district.id', read_only=True)

	class Meta(LocationSerializer.Meta):
		model = Municipality
		fields = ['id', 'name', 'district_id']


class SchoolSerializer(serializers.ModelSerializer):
	municipality_id = serializers.IntegerField(
		source='municipality.id',
		read_only=True
	)

	class Meta:
		model = School
		fields = ['id', 'name', 'logo_url', 'sector', 'municipality_id']


class GradeSerializer(LocationSerializer):
	class Meta(LocationSerializer.Meta):
		model = Grade


def _validate_location_chain(province, district, municipality, school):
	if not province or not district:
		raise serializers.ValidationError(
			'Province and district are required for registration.'
		)

	if district.province_id != province.id:
		raise serializers.ValidationError({
			'district_id':
				'District does not belong to the selected province.'
		})

	if municipality and municipality.district_id != district.id:
		raise serializers.ValidationError({
			'municipality_id':
				'Municipality does not belong to the selected district.'
		})

	if school and municipality:
		if school.municipality_id != municipality.id:
			raise serializers.ValidationError({
				'school_id':
					'School does not belong to the selected municipality.'
			})


class RegistrationSerializer(serializers.Serializer):
	email = serializers.EmailField()
	password = serializers.CharField(write_only=True, min_length=8)
	confirm_password = serializers.CharField(write_only=True, min_length=8)
	name = serializers.CharField(max_length=150)
	gender = serializers.ChoiceField(choices=['male', 'female', 'other'])
	dob = serializers.DateField(input_formats=['%d/%m/%Y', '%Y-%m-%d'])
	phone_country_code = serializers.CharField(max_length=8)
	phone_number = serializers.CharField(max_length=30)
	location = serializers.CharField(max_length=255)

	profile_photo = serializers.FileField(
		required=False,
		allow_null=True,
		write_only=True
	)

	def validate_profile_photo(self, uploaded_file):
		return validate_profile_photo_file(uploaded_file)

	def validate_email(self, value):
		value = value.strip().lower()

		if User.objects.filter(email__iexact=value).exists():
			raise serializers.ValidationError(
				'A user with this email already exists.',
				code='EMAIL_ALREADY_REGISTERED',
			)

		return value

	def validate_password(self, value):
		try:
			validate_password(value)
		except DjangoValidationError as exc:
			raise serializers.ValidationError(list(exc.messages))
		return value

	def validate(self, attrs):
		if attrs['password'] != attrs['confirm_password']:
			raise serializers.ValidationError({
				'confirm_password': 'Passwords do not match.'
			})

		return attrs

	def _save_upload(self, uploaded_file, folder, user_id):
		return save_upload(uploaded_file, folder, user_id)

	def _create_user(self, validated_data, role_name, onboarding_completed):
		profile_photo = validated_data.pop('profile_photo', None)
		validated_data.pop('confirm_password', None)

		password = validated_data.pop('password')

		user = User(
			email=validated_data.pop('email'),
			**validated_data
		)

		user.set_password(password)
		user.role = user_role(role_name)
		user.onboarding_completed = onboarding_completed
		if role_name in ('student', 'instructor'):
			user.email_verified = False
		user.verification_status = (
			'pending' if role_name == 'instructor' else 'not_applicable'
		)
		user.save()

		if profile_photo:
			user.profile_photo_url = self._save_upload(
				profile_photo,
				'profile-photos',
				user.pk
			)

			user.save(
				update_fields=['profile_photo_url', 'updated_at']
			)

		return user


class StudentRegistrationSerializer(RegistrationSerializer):
	phone_country_code = serializers.CharField(max_length=8, required=False, allow_blank=True)
	phone_number = serializers.CharField(max_length=30, required=False, allow_blank=True)
	location = serializers.CharField(max_length=255, required=False, allow_blank=True)

	student_id_card = serializers.FileField(
		required=False,
		allow_null=True,
		write_only=True
	)

	def validate_student_id_card(self, uploaded_file):
		return validate_student_id_card_file(uploaded_file)

	@transaction.atomic
	def create(self, validated_data):
		student_id_card = validated_data.pop('student_id_card', None)

		user = self._create_user(
			validated_data,
			'student',
			onboarding_completed=False,
		)

		profile = StudentProfile.objects.create(
			user=user,
			onboarding_flow_version=StudentProfile.INTERESTS_ONBOARDING,
			grade=None,
			province=None,
			district=None,
			municipality=None,
			school=None,
		)
		user.onboarding_step = 2
		user.save(update_fields=['onboarding_step', 'updated_at'])

		if student_id_card:
			document = VerificationDocument.objects.create(
				user=user,
				document_type='student_id_card',
				file_url=self._save_upload(
					student_id_card,
					'verification-documents',
					user.pk
				),
			)

			profile.student_id_card_document = document
			profile.save(
				update_fields=['student_id_card_document']
			)

		issue_signup_otp(user)
		return user


class InstructorRegistrationSerializer(RegistrationSerializer):
	# Overrides the base RegistrationSerializer's required phone/location —
	# deferred to InstructorCompleteProfileSerializer, same pattern as A1.
	phone_country_code = serializers.CharField(
		max_length=8,
		required=False,
		allow_blank=True,
		default=''
	)

	phone_number = serializers.CharField(
		max_length=30,
		required=False,
		allow_blank=True,
		default=''
	)

	location = serializers.CharField(
		max_length=255,
		required=False,
		allow_blank=True,
		default=''
	)

	province_id = serializers.PrimaryKeyRelatedField(
		queryset=Province.objects.all(),
		source='province',
		required=False,
		allow_null=True,
	)

	district_id = serializers.PrimaryKeyRelatedField(
		queryset=District.objects.select_related('province').all(),
		source='district',
		required=False,
		allow_null=True,
	)

	municipality_id = serializers.PrimaryKeyRelatedField(
		queryset=Municipality.objects.select_related('district').all(),
		source='municipality',
		required=False,
		allow_null=True,
	)

	school_id = serializers.PrimaryKeyRelatedField(
		queryset=School.objects.select_related(
			'municipality__district'
		).all(),
		source='school',
		required=False,
		allow_null=True,
	)

	qualification = serializers.CharField(
		max_length=255,
		required=False,
		allow_blank=True,
		default=''
	)

	subject_expertise = serializers.CharField(
		required=False,
		allow_blank=True,
		default=''
	)

	experience_years = serializers.IntegerField(
		min_value=0,
		max_value=100,
		required=False,
		allow_null=True,
	)

	cv_resume = serializers.FileField(
		required=False,
		allow_null=True,
		write_only=True
	)

	certificates_and_recommendations = serializers.ListField(
		child=serializers.FileField(),
		required=False,
		write_only=True,
	)

	def validate_cv_resume(self, uploaded_file):
		if uploaded_file is None:
			return None
		return validate_cv_resume_file(uploaded_file)

	def validate_certificates_and_recommendations(self, uploaded_files):
		return validate_certificate_files(uploaded_files)

	def validate(self, attrs):
		attrs = super().validate(attrs)

		# Only enforce the chain if the instructor supplied any part of it —
		# it's deferred entirely to complete-profile otherwise.
		if attrs.get('province') or attrs.get('district'):
			_validate_location_chain(
				attrs.get('province'),
				attrs.get('district'),
				attrs.get('municipality'),
				attrs.get('school'),
			)

		return attrs

	@transaction.atomic
	def create(self, validated_data):
		cv_resume = validated_data.pop('cv_resume', None)

		documents = validated_data.pop(
			'certificates_and_recommendations',
			[]
		)

		qualification = validated_data.pop('qualification', '')
		subject_expertise = validated_data.pop('subject_expertise', '')
		experience_years = validated_data.pop('experience_years', None)
		province = validated_data.pop('province', None)
		district = validated_data.pop('district', None)
		municipality = validated_data.pop('municipality', None)
		school = validated_data.pop('school', None)

		user = self._create_user(
			validated_data,
			'instructor',
			onboarding_completed=True,
		)

		profile = InstructorProfile.objects.create(
			user=user,
			province=province,
			district=district,
			municipality=municipality,
			school=school,
			qualification=qualification,
			subject_expertise=subject_expertise,
			experience_years=experience_years,
		)

		if cv_resume:
			profile.cv_resume_document = VerificationDocument.objects.create(
				user=user,
				document_type='cv_resume',
				file_url=self._save_upload(
					cv_resume,
					'verification-documents',
					user.pk
				),
			)
			profile.save(update_fields=['cv_resume_document'])

		for uploaded_file in documents:
			VerificationDocument.objects.create(
				user=user,
				document_type='certificate',
				file_url=self._save_upload(
					uploaded_file,
					'verification-documents',
					user.pk
				),
			)

		issue_signup_otp(user)
		return user


class CompleteStudentProfileSerializer(serializers.Serializer):
	phone_country_code = serializers.CharField(max_length=8)
	phone_number = serializers.CharField(max_length=30)
	location = serializers.CharField(max_length=255)

	grade_id = serializers.PrimaryKeyRelatedField(
		queryset=Grade.objects.all(),
		source='grade'
	)

	province_id = serializers.PrimaryKeyRelatedField(
		queryset=Province.objects.all(),
		source='province'
	)

	district_id = serializers.PrimaryKeyRelatedField(
		queryset=District.objects.select_related('province').all(),
		source='district'
	)

	municipality_id = serializers.PrimaryKeyRelatedField(
		queryset=Municipality.objects.select_related('district').all(),
		source='municipality',
		required=False,
		allow_null=True,
	)

	school_id = serializers.PrimaryKeyRelatedField(
		queryset=School.objects.select_related(
			'municipality__district'
		).all(),
		source='school'
	)

	def validate(self, attrs):
		# The student form has no municipality step; take it from the school
		# so the school is still checked against the chosen district.
		if not attrs.get('municipality') and attrs.get('school'):
			attrs['municipality'] = attrs['school'].municipality

		_validate_location_chain(
			attrs.get('province'),
			attrs.get('district'),
			attrs.get('municipality'),
			attrs.get('school'),
		)

		return attrs

	@transaction.atomic
	def save(self):
		user = User.objects.select_for_update().get(pk=self.context['request'].user.pk)
		profile = user.student_profile

		profile.grade = self.validated_data['grade']
		profile.province = self.validated_data['province']
		profile.district = self.validated_data['district']
		profile.municipality = self.validated_data.get('municipality')
		profile.school = self.validated_data['school']
		profile.profile_completed = True
		profile.save(update_fields=[
			'grade', 'province', 'district', 'municipality', 'school', 'profile_completed'
		])

		user.phone_country_code = self.validated_data['phone_country_code']
		user.phone_number = self.validated_data['phone_number']
		user.location = self.validated_data['location']
		update_student_onboarding(user, profile)
		user.save(update_fields=[
			'phone_country_code',
			'phone_number',
			'location',
			'onboarding_completed',
			'onboarding_step',
			'updated_at',
		])
		self.context['request'].user.refresh_from_db()

		return profile


class InstructorCompleteProfileSerializer(serializers.Serializer):
	phone_country_code = serializers.CharField(max_length=8)
	phone_number = serializers.CharField(max_length=30)
	location = serializers.CharField(max_length=255)

	province_id = serializers.PrimaryKeyRelatedField(
		queryset=Province.objects.all(),
		source='province'
	)

	district_id = serializers.PrimaryKeyRelatedField(
		queryset=District.objects.select_related('province').all(),
		source='district'
	)

	municipality_id = serializers.PrimaryKeyRelatedField(
		queryset=Municipality.objects.select_related('district').all(),
		source='municipality'
	)

	school_id = serializers.PrimaryKeyRelatedField(
		queryset=School.objects.select_related(
			'municipality__district'
		).all(),
		source='school',
		required=False,
		allow_null=True,
	)

	qualification = serializers.CharField(max_length=255)
	subject_expertise = serializers.CharField()

	experience_years = serializers.IntegerField(
		min_value=0,
		max_value=100,
	)

	def validate(self, attrs):
		_validate_location_chain(
			attrs.get('province'),
			attrs.get('district'),
			attrs.get('municipality'),
			attrs.get('school'),
		)

		return attrs

	def save(self):
		user = self.context['request'].user
		profile = user.instructor_profile

		profile.province = self.validated_data['province']
		profile.district = self.validated_data['district']
		profile.municipality = self.validated_data['municipality']
		profile.school = self.validated_data.get('school')
		profile.qualification = self.validated_data['qualification']
		profile.subject_expertise = self.validated_data['subject_expertise']
		profile.experience_years = self.validated_data['experience_years']
		profile.save(update_fields=[
			'province', 'district', 'municipality', 'school',
			'qualification', 'subject_expertise', 'experience_years',
		])

		user.phone_country_code = self.validated_data['phone_country_code']
		user.phone_number = self.validated_data['phone_number']
		user.location = self.validated_data['location']
		user.save(update_fields=[
			'phone_country_code', 'phone_number', 'location', 'updated_at'
		])

		return profile


class CurrentUserUpdateSerializer(serializers.Serializer):
	name = serializers.CharField(max_length=150, required=False)
	email = serializers.EmailField(required=False)
	gender = serializers.ChoiceField(
		choices=['male', 'female', 'other'],
		required=False,
	)
	dob = serializers.DateField(
		input_formats=['%d/%m/%Y', '%Y-%m-%d'],
		required=False,
	)
	phone_country_code = serializers.CharField(
		max_length=8, required=False, allow_blank=True
	)
	phone_number = serializers.CharField(
		max_length=30, required=False, allow_blank=True
	)
	location = serializers.CharField(
		max_length=255, required=False, allow_blank=True
	)

	profile_photo = serializers.FileField(required=False, write_only=True)
	student_id_card = serializers.FileField(required=False, write_only=True)
	cv_resume = serializers.FileField(required=False, write_only=True)
	certificates_and_recommendations = serializers.ListField(
		child=serializers.FileField(),
		required=False,
		write_only=True,
	)

	STUDENT_ONLY_FIELDS = ('student_id_card',)
	INSTRUCTOR_ONLY_FIELDS = ('cv_resume', 'certificates_and_recommendations')

	def validate_profile_photo(self, uploaded_file):
		return validate_profile_photo_file(uploaded_file)

	def validate_student_id_card(self, uploaded_file):
		return validate_student_id_card_file(uploaded_file)

	def validate_cv_resume(self, uploaded_file):
		return validate_cv_resume_file(uploaded_file)

	def validate_certificates_and_recommendations(self, uploaded_files):
		return validate_certificate_files(uploaded_files)

	def validate(self, attrs):
		user = self.context['request'].user
		role_name = user.role.name if user.role else None
		errors = {}

		if role_name != 'student':
			for field in self.STUDENT_ONLY_FIELDS:
				if field in attrs:
					errors[field] = 'Only students can upload this document.'

		if role_name != 'instructor':
			for field in self.INSTRUCTOR_ONLY_FIELDS:
				if field in attrs:
					errors[field] = 'Only instructors can upload this document.'

		if errors:
			raise serializers.ValidationError(errors)

		return attrs

	def validate_email(self, value):
		value = value.strip().lower()
		user = self.context['request'].user

		if User.objects.filter(
			email__iexact=value
		).exclude(pk=user.pk).exists():
			raise serializers.ValidationError(
				'A user with this email already exists.',
				code='EMAIL_ALREADY_REGISTERED',
			)

		return value

	@transaction.atomic
	def save(self):
		user = self.context['request'].user
		data = self.validated_data
		updated_fields = []

		for field in (
			'name', 'email', 'gender', 'dob',
			'phone_country_code', 'phone_number', 'location',
		):
			if field in data:
				setattr(user, field, data[field])
				updated_fields.append(field)

		if 'profile_photo' in data:
			user.profile_photo_url = save_upload(
				data['profile_photo'], 'profile-photos', user.pk
			)
			updated_fields.append('profile_photo_url')

		if updated_fields:
			updated_fields.append('updated_at')
			user.save(update_fields=updated_fields)

		# Replacing a document adds a new VerificationDocument and repoints the
		# profile at it; earlier rows are kept as review history.
		if 'student_id_card' in data:
			profile = user.student_profile
			profile.student_id_card_document = self._create_document(
				user, 'student_id_card', data['student_id_card']
			)
			profile.save(update_fields=['student_id_card_document'])

		if 'cv_resume' in data:
			profile = user.instructor_profile
			profile.cv_resume_document = self._create_document(
				user, 'cv_resume', data['cv_resume']
			)
			profile.save(update_fields=['cv_resume_document'])

		# Certificates are a collection, so uploads add to it.
		for uploaded_file in data.get('certificates_and_recommendations', []):
			self._create_document(user, 'certificate', uploaded_file)

		return user

	def _create_document(self, user, document_type, uploaded_file):
		return VerificationDocument.objects.create(
			user=user,
			document_type=document_type,
			file_url=save_upload(
				uploaded_file, 'verification-documents', user.pk
			),
		)


class LoginSerializer(serializers.Serializer):
	email = serializers.EmailField()
	password = serializers.CharField(write_only=True)

	def validate(self, attrs):
		email = attrs.get('email')
		password = attrs.get('password')

		try:
			user = User.objects.get(email__iexact=email)
		except User.DoesNotExist:
			raise serializers.ValidationError({
				'detail': 'Invalid email or password.'
			})

		if not user.check_password(password):
			raise serializers.ValidationError({
				'detail': 'Invalid email or password.'
			})

		if not user.is_active:
			raise serializers.ValidationError({
				'detail': 'This account is inactive.'
			})

		if user.role.name in ('student', 'instructor') and not user.email_verified:
			raise serializers.ValidationError({'detail': 'Verify your email before signing in.'})

		attrs['user'] = user
		return attrs


PASSWORD_RESET_OTP_MAX_ATTEMPTS = 5


def _password_state(user):
	return salted_hmac(
		'skillsikka-password-reset-state',
		user.password
	).hexdigest()


class ForgotPasswordSerializer(serializers.Serializer):
	email = serializers.EmailField()

	def validate_email(self, value):
		return value.strip().lower()

	def save(self):
		email = self.validated_data['email']

		try:
			user = User.objects.get(email__iexact=email)
		except User.DoesNotExist:
			return

		otp = f'{secrets.randbelow(10000):04d}'

		PasswordResetOTP.objects.filter(
			user=user,
			is_used=False
		).update(is_used=True)

		PasswordResetOTP.objects.create(
			user=user,
			otp_hash=make_password(otp),
			expires_at=timezone.now() + timedelta(seconds=OTP_EXPIRY_SECONDS),
		)

		send_mail(
			subject='SkillSikka Password Reset OTP',
			message=(
				f'Your SkillSikka password reset OTP is {otp}. '
				f'This OTP will expire in {OTP_EXPIRY_TEXT}.'
			),
			from_email=getattr(
				settings,
				'DEFAULT_FROM_EMAIL',
				'noreply@skillsikka.com'
			),
			recipient_list=[user.email],
			fail_silently=False,
		)


class VerifyPasswordResetOTPSerializer(serializers.Serializer):
	email = serializers.EmailField()

	otp = serializers.RegexField(
		regex=r'^[0-9]{4}$',
		min_length=4,
		max_length=4,
		trim_whitespace=False,
		write_only=True,
		error_messages={'invalid': 'Enter exactly 4 numeric digits.'},
	)

	def validate_otp(self, value):
		if not isinstance(self.initial_data.get('otp'), str):
			raise serializers.ValidationError('Enter exactly 4 numeric digits as a string.')
		return value

	def validate(self, attrs):
		email = attrs['email'].strip().lower()
		otp = attrs['otp']

		invalid = serializers.ValidationError({
			'detail': 'Invalid or expired OTP.'
		})

		try:
			user = User.objects.get(email__iexact=email)
		except User.DoesNotExist:
			raise invalid

		# Decide inside the lock, raise outside it, so a failed attempt
		# is committed rather than rolled back with the error.
		with transaction.atomic():
			otp_record = PasswordResetOTP.objects.select_for_update().filter(
				user=user,
				is_used=False
			).order_by('-created_at').first()

			verified = False

			if otp_record is None:
				pass
			elif (
				otp_record.expires_at < timezone.now()
				or otp_record.failed_attempts >= PASSWORD_RESET_OTP_MAX_ATTEMPTS
			):
				otp_record.is_used = True
				otp_record.save(update_fields=['is_used'])
			elif not check_password(otp, otp_record.otp_hash):
				otp_record.failed_attempts += 1
				otp_record.is_used = (
					otp_record.failed_attempts
					>= PASSWORD_RESET_OTP_MAX_ATTEMPTS
				)
				otp_record.save(update_fields=['failed_attempts', 'is_used'])
			else:
				otp_record.is_used = True
				otp_record.save(update_fields=['is_used'])
				verified = True

		if not verified:
			raise invalid

		signer = TimestampSigner(
			salt='skillsikka-password-reset'
		)

		reset_token = signer.sign_object({
			'user_id': str(user.pk),
			'purpose': 'password_reset',
			'state': _password_state(user),
		})

		attrs['reset_token'] = reset_token

		return attrs


class ResetPasswordSerializer(serializers.Serializer):
	reset_token = serializers.CharField(write_only=True)

	new_password = serializers.CharField(
		write_only=True,
		min_length=8
	)

	confirm_password = serializers.CharField(
		write_only=True,
		min_length=8
	)

	def validate(self, attrs):
		if attrs['new_password'] != attrs['confirm_password']:
			raise serializers.ValidationError({
				'confirm_password': 'Passwords do not match.'
			})

		signer = TimestampSigner(
			salt='skillsikka-password-reset'
		)

		try:
			data = signer.unsign_object(
				attrs['reset_token'],
				max_age=600
			)
		except (BadSignature, SignatureExpired):
			raise serializers.ValidationError({
				'detail': 'Invalid or expired reset token.'
			})

		if data.get('purpose') != 'password_reset':
			raise serializers.ValidationError({
				'detail': 'Invalid reset token.'
			})

		try:
			user = User.objects.get(pk=data['user_id'])
		except User.DoesNotExist:
			raise serializers.ValidationError({
				'detail': 'Invalid reset token.'
			})

		# The token is bound to the current password hash, so it stops
		# working as soon as it has been used once.
		if not constant_time_compare(
			data.get('state', ''),
			_password_state(user)
		):
			raise serializers.ValidationError({
				'detail': 'Invalid or expired reset token.'
			})

		try:
			validate_password(attrs['new_password'], user=user)
		except DjangoValidationError as exc:
			raise serializers.ValidationError({
				'new_password': list(exc.messages)
			})

		attrs['user'] = user

		return attrs

	@transaction.atomic
	def save(self):
		user = self.validated_data['user']
		new_password = self.validated_data['new_password']

		user.set_password(new_password)
		user.save(update_fields=['password'])

		# Sign out every existing session for this account.
		for token in OutstandingToken.objects.filter(user=user):
			BlacklistedToken.objects.get_or_create(token=token)

		return user


def user_role(role_name):
	from .models import Role
	return Role.objects.get(name=role_name)


class SubjectSerializer(serializers.ModelSerializer):
	class Meta:
		model = Subject
		fields = ['id', 'name']


class ChapterSerializer(serializers.ModelSerializer):
	subject_name = serializers.CharField(
		source='subject.name',
		read_only=True
	)
	grade_name = serializers.CharField(
		source='grade.name',
		read_only=True
	)

	class Meta:
		model = Chapter
		fields = [
			'id',
			'subject',
			'subject_name',
			'grade',
			'grade_name',
			'name',
			'order',
		]


class TopicSerializer(serializers.ModelSerializer):
	chapter_name = serializers.CharField(
		source='chapter.name',
		read_only=True
	)

	class Meta:
		model = Topic
		fields = [
			'id',
			'chapter',
			'chapter_name',
			'name',
			'order',
		]


class CourseReviewSerializer(serializers.ModelSerializer):
	student = serializers.SerializerMethodField()
	rating = serializers.IntegerField(min_value=1, max_value=5)

	class Meta:
		model = CourseReview
		fields = ['id', 'rating', 'review', 'student', 'created_at', 'updated_at']
		read_only_fields = ['id', 'student', 'created_at', 'updated_at']

	def get_student(self, obj):
		return {'id': obj.student_id, 'name': obj.student.name}

	def reject_identity_fields(self, data):
		if not isinstance(data, Mapping):
			raise serializers.ValidationError({'detail': 'Expected an object.'})
		forbidden = set(data) & {
			'student', 'student_id', 'user', 'user_id',
			'course', 'course_id', 'instructor', 'instructor_id',
		}
		if forbidden:
			raise serializers.ValidationError({key: 'This field cannot be supplied.' for key in sorted(forbidden)})

	def to_internal_value(self, data):
		self.reject_identity_fields(data)
		if 'rating' in data:
			rating = data['rating']
			# DRF accepts whole floats; reviews deliberately require integers.
			if (
				isinstance(rating, bool)
				or not isinstance(rating, (int, str))
				or (isinstance(rating, str) and not rating.strip().isdigit())
			):
				raise serializers.ValidationError({'rating': 'A valid integer is required.'})
		return super().to_internal_value(data)


class PublicInstructorSerializer(serializers.ModelSerializer):
	profile_photo_url = serializers.SerializerMethodField()
	qualification = serializers.SerializerMethodField()
	subject_expertise = serializers.SerializerMethodField()
	average_rating = serializers.FloatField(read_only=True, allow_null=True)
	review_count = serializers.IntegerField(read_only=True)
	total_students = serializers.IntegerField(read_only=True)
	total_courses = serializers.IntegerField(read_only=True)

	def get_profile_photo_url(self, obj):
		photo = obj.profile_photo_src
		request = self.context.get('request')
		return request.build_absolute_uri(photo) if photo and request else photo

	def get_qualification(self, obj):
		return getattr(getattr(obj, 'instructor_profile', None), 'qualification', '')

	def get_subject_expertise(self, obj):
		return getattr(getattr(obj, 'instructor_profile', None), 'subject_expertise', '')

	class Meta:
		model = User
		fields = ['id', 'name', 'profile_photo_url', 'qualification', 'subject_expertise',
			'average_rating', 'review_count', 'total_students', 'total_courses']
		read_only_fields = fields


class CourseSerializer(serializers.ModelSerializer):
	average_rating = serializers.SerializerMethodField()
	review_count = serializers.SerializerMethodField()

	def _review_stats(self, obj):
		if not hasattr(obj, '_serialized_review_stats'):
			from django.db.models import Avg, Count
			obj._serialized_review_stats = obj.reviews.aggregate(average_rating=Avg('rating'), review_count=Count('pk'))
		return obj._serialized_review_stats

	def get_average_rating(self, obj):
		return obj.average_rating if hasattr(obj, 'average_rating') else self._review_stats(obj)['average_rating']

	def get_review_count(self, obj):
		return obj.review_count if hasattr(obj, 'review_count') else self._review_stats(obj)['review_count']

	instructor_name = serializers.CharField(
		source='instructor.name',
		read_only=True
	)
	subject_name = serializers.CharField(
		source='subject.name',
		read_only=True
	)
	grade_name = serializers.CharField(
		source='grade.name',
		read_only=True
	)

	class Meta:
		model = Course
		fields = [
			'id',
			'average_rating',
			'review_count',
			'title',
			'description',
			'instructor',
			'instructor_name',
			'course_type',
			'subject',
			'subject_name',
			'grade',
			'grade_name',
			'is_paid',
			'price',
			'thumbnail_url',
			'is_published',
			'created_at',
			'updated_at',
		]
		read_only_fields = [
			'instructor',
			'created_at',
			'updated_at',
		]

	def validate(self, attrs):
		course_type = attrs.get(
			'course_type',
			getattr(self.instance, 'course_type', None)
		)
		subject = attrs.get(
			'subject',
			getattr(self.instance, 'subject', None)
		)
		grade = attrs.get(
			'grade',
			getattr(self.instance, 'grade', None)
		)
		is_paid = attrs.get(
			'is_paid',
			getattr(self.instance, 'is_paid', False)
		)
		price = attrs.get(
			'price',
			getattr(self.instance, 'price', None)
		)

		if course_type == 'academic':
			if subject is None:
				raise serializers.ValidationError({
					'subject': 'Subject is required for an academic course.'
				})
			if grade is None:
				raise serializers.ValidationError({
					'grade': 'Grade is required for an academic course.'
				})

		elif course_type == 'skill':
			attrs['subject'] = None
			attrs['grade'] = None

		if is_paid:
			if price is None or price <= 0:
				raise serializers.ValidationError({
					'price': 'A paid course must have a price greater than 0.'
				})
		else:
			attrs['price'] = None

		return attrs


class HomeCourseSerializer(CourseSerializer):
	is_enrolled = serializers.BooleanField(read_only=True)

	class Meta(CourseSerializer.Meta):
		fields = CourseSerializer.Meta.fields + ['is_enrolled']


class LessonSerializer(serializers.ModelSerializer):
	topic_name = serializers.CharField(
		source='topic.name',
		read_only=True
	)
	course_title = serializers.CharField(
		source='course.title',
		read_only=True
	)

	class Meta:
		model = Lesson
		fields = [
			'id',
			'topic',
			'topic_name',
			'course',
			'course_title',
			'title',
			'content_type',
			'content_url',
			'content_text',
			'order',
			'created_at',
		]
		read_only_fields = ['created_at']

	def validate(self, attrs):
		topic = attrs.get(
			'topic',
			getattr(self.instance, 'topic', None)
		)

		course = attrs.get(
			'course',
			getattr(self.instance, 'course', None)
		)

		content_type = attrs.get(
			'content_type',
			getattr(self.instance, 'content_type', None)
		)

		content_url = attrs.get(
			'content_url',
			getattr(self.instance, 'content_url', '')
		)

		content_text = attrs.get(
			'content_text',
			getattr(self.instance, 'content_text', '')
		)

		if course is None:
			raise serializers.ValidationError({
				'course': 'A lesson must belong to a course.'
			})

		if course.course_type == 'academic':
			if course.subject is None or course.grade is None:
				raise serializers.ValidationError({
					'course': (
						'An academic course must have a subject '
						'and grade.'
					)
				})

			if topic is not None:
				if (
					topic.chapter.subject_id != course.subject_id
					or
					topic.chapter.grade_id != course.grade_id
				):
					raise serializers.ValidationError({
						'topic': (
							'The selected topic does not belong '
							'to the same subject and grade as '
							'this academic course.'
						)
					})

		elif course.course_type == 'skill':
			if topic is not None:
				raise serializers.ValidationError({
					'topic': (
						'Skill course lessons cannot be linked '
						'to an academic topic.'
					)
				})

		if content_type == 'text':
			if not content_text:
				raise serializers.ValidationError({
					'content_text': (
						'Text content is required for a text lesson.'
					)
				})

		else:
			if not content_url:
				raise serializers.ValidationError({
					'content_url': (
						'A content URL is required for this lesson type.'
					)
				})

		return attrs


class EnrollmentSerializer(serializers.ModelSerializer):
	course_title = serializers.CharField(source='course.title', read_only=True)
	course_thumbnail_url = serializers.CharField(source='course.thumbnail_url', read_only=True)

	class Meta:
		model = Enrollment
		fields = [
			'id', 'course', 'course_title', 'course_thumbnail_url',
			'status', 'amount_paid', 'payment_reference',
			'enrolled_at', 'completed_at',
		]
		read_only_fields = ['id', 'status', 'enrolled_at', 'completed_at']


class EnrollCourseSerializer(serializers.Serializer):
	def validate(self, attrs):
		course = self.context['course']
		student = self.context['request'].user

		if course.course_type != 'skill':
			raise serializers.ValidationError({
				'detail': 'Only skill development courses require enrollment.'
			})

		if not course.is_published:
			raise serializers.ValidationError({
				'detail': 'This course is not available for enrollment.'
			})

		if Enrollment.objects.filter(student=student, course=course).exists():
			raise serializers.ValidationError({
				'detail': 'You are already enrolled in this course.'
			})

		return attrs

	def create(self, validated_data):
		course = self.context['course']
		student = self.context['request'].user

		enrollment_status = 'pending_payment' if course.is_paid else 'active'

		return Enrollment.objects.create(
			student=student,
			course=course,
			status=enrollment_status,
			amount_paid=course.price if not course.is_paid else None,
		)


class ResumeLessonSerializer(serializers.Serializer):
	id = serializers.IntegerField(read_only=True)
	title = serializers.CharField(read_only=True)
	content_type = serializers.CharField(read_only=True)
	order = serializers.IntegerField(read_only=True)
	lesson_number = serializers.IntegerField(read_only=True)


class LearningCourseSerializer(serializers.Serializer):
	enrollment_id = serializers.IntegerField(read_only=True)
	enrollment_status = serializers.CharField(read_only=True)
	enrolled_at = serializers.DateTimeField(read_only=True)
	completed_at = serializers.DateTimeField(read_only=True, allow_null=True)
	course = CourseSerializer(read_only=True)
	progress_percentage = serializers.FloatField(read_only=True)
	completed_lessons = serializers.IntegerField(read_only=True)
	total_lessons = serializers.IntegerField(read_only=True)
	is_completed = serializers.BooleanField(read_only=True)
	next_lesson = ResumeLessonSerializer(read_only=True, allow_null=True)
	resume_url = serializers.CharField(read_only=True, allow_null=True)
	last_learning_activity = serializers.DateTimeField(read_only=True, allow_null=True)


class LessonProgressSerializer(serializers.ModelSerializer):
	lesson_title = serializers.CharField(source='lesson.title', read_only=True)

	class Meta:
		model = LessonProgress
		fields = ['id', 'lesson', 'lesson_title', 'is_completed', 'completed_at']
		read_only_fields = ['id', 'lesson_title', 'completed_at']


class CourseProgressSerializer(serializers.Serializer):
	course_id = serializers.IntegerField()
	total_lessons = serializers.IntegerField()
	completed_lessons = serializers.IntegerField()
	progress_percentage = serializers.FloatField()
	is_completed = serializers.BooleanField()


class PaymentSerializer(serializers.ModelSerializer):
	course_title = serializers.CharField(source='course.title', read_only=True)

	class Meta:
		model = Payment
		fields = [
			'id', 'course', 'course_title', 'enrollment', 'amount',
			'provider', 'transaction_reference', 'status',
			'gateway_transaction_id', 'created_at', 'verified_at',
		]
		read_only_fields = ['id', 'status', 'created_at', 'verified_at']


class InitiatePaymentSerializer(serializers.Serializer):
	provider = serializers.ChoiceField(choices=Payment.PROVIDER_CHOICES)

	def validate(self, attrs):
		course = self.context['course']
		student = self.context['request'].user

		if not course.is_paid:
			raise serializers.ValidationError({
				'detail': 'This course is free and does not require payment.'
			})

		if course.price is None or course.price <= 0:
			raise serializers.ValidationError({
				'detail': 'This course has no price set yet. Please contact support.'
			})

		enrollment = Enrollment.objects.filter(student=student, course=course).first()
		if enrollment is None:
			raise serializers.ValidationError({
				'detail': 'You must enroll in this course before initiating payment.'
			})

		if enrollment.status == 'active' or enrollment.status == 'completed':
			raise serializers.ValidationError({
				'detail': 'This enrollment is already active.'
			})

		attrs['enrollment'] = enrollment
		attrs['course'] = course
		return attrs

	def create(self, validated_data):
		import uuid
		enrollment = validated_data['enrollment']
		course = validated_data['course']
		student = self.context['request'].user

		return Payment.objects.create(
			student=student,
			course=course,
			enrollment=enrollment,
			amount=course.price,
			provider=validated_data['provider'],
			transaction_reference=str(uuid.uuid4()),
			status='initiated',
		)


class VerifyPaymentSerializer(serializers.Serializer):
	"""Asks the gateway for the real outcome; the client's word is not used."""

	transaction_reference = serializers.CharField()

	def validate(self, attrs):
		payment = Payment.objects.filter(
			transaction_reference=attrs['transaction_reference'],
		).first()

		if payment is None:
			raise serializers.ValidationError({'detail': 'Payment not found.'})

		if payment.student_id != self.context['request'].user.id:
			raise serializers.ValidationError({'detail': 'This payment does not belong to you.'})

		attrs['payment'] = payment
		return attrs


class QuestionOptionManagementSerializer(serializers.ModelSerializer):
	class Meta:
		model = QuestionOption
		fields = [
			'id',
			'question',
			'text',
			'is_correct',
		]
		read_only_fields = ['id']


class QuestionManagementSerializer(serializers.ModelSerializer):
	options = QuestionOptionManagementSerializer(
		many=True,
		read_only=True
	)

	class Meta:
		model = Question
		fields = [
			'id',
			'quiz',
			'text',
			'marks',
			'points',
			'order',
			'options',
		]
		read_only_fields = ['id']

	def validate_marks(self, value):
		if value < 1:
			raise serializers.ValidationError(
				'Marks must be at least 1.'
			)

		return value


class QuizManagementSerializer(serializers.ModelSerializer):
	questions = QuestionManagementSerializer(
		many=True,
		read_only=True
	)

	course_title = serializers.CharField(
		source='course.title',
		read_only=True
	)

	class Meta:
		model = Quiz
		fields = [
			'id',
			'course',
			'course_title',
			'title',
			'description',
			'pass_percentage',
			'max_attempts',
			'is_published',
			'questions',
			'created_at',
			'updated_at',
		]
		read_only_fields = [
			'id',
			'created_at',
			'updated_at',
		]

	def validate_pass_percentage(self, value):
		if value < 0 or value > 100:
			raise serializers.ValidationError(
				'Pass percentage must be '
				'between 0 and 100.'
			)

		return value

	def validate_max_attempts(self, value):
		if value < 1:
			raise serializers.ValidationError(
				'Maximum attempts must be '
				'at least 1.'
			)

		return value

	def validate(self, attrs):
		attrs = super().validate(attrs)

		instance = self.instance

		course = attrs.get(
			'course',
			instance.course if instance else None
		)

		is_published = attrs.get(
			'is_published',
			instance.is_published if instance else False
		)

		if not is_published:
			return attrs

		if not course.is_published:
			raise serializers.ValidationError({
				'is_published':
					'The course must be published before its quiz can be published.'
			})

		if instance is None:
			raise serializers.ValidationError({
				'is_published':
					'Create the quiz as draft, add questions and options, then publish it.'
			})

		questions = instance.questions.prefetch_related(
			'options'
		).all()

		if not questions.exists():
			raise serializers.ValidationError({
				'is_published':
					'A quiz must contain at least one question before publishing.'
			})

		for question in questions:
			options = list(question.options.all())

			if len(options) < 2:
				raise serializers.ValidationError({
					'is_published':
						f'Question {question.id} must have at least two options.'
				})

			correct_count = sum(
				1 for option in options
				if option.is_correct
			)

			if correct_count != 1:
				raise serializers.ValidationError({
					'is_published':
						f'Question {question.id} must have exactly one correct option.'
				})

		request = self.context.get('request')

		if request:
			user = request.user

			role_name = getattr(
				getattr(user, 'role', None),
				'name',
				''
			)

			is_admin = (
				user.is_superuser
				or role_name == 'super_admin'
			)

			if (
				not is_admin
				and user.verification_status != 'verified'
			):
				raise serializers.ValidationError({
					'is_published':
						'Only verified instructors can publish quizzes.'
				})

		return attrs


class QuestionOptionStudentSerializer(serializers.ModelSerializer):
	class Meta:
		model = QuestionOption
		fields = [
			'id',
			'text',
		]


class QuestionStudentSerializer(serializers.ModelSerializer):
	options = QuestionOptionStudentSerializer(
		many=True,
		read_only=True
	)

	class Meta:
		model = Question
		fields = [
			'id',
			'text',
			'marks',
			'order',
			'options',
		]


class QuizStudentSerializer(serializers.ModelSerializer):
	questions = QuestionStudentSerializer(
		many=True,
		read_only=True
	)

	course_title = serializers.CharField(
		source='course.title',
		read_only=True
	)

	class Meta:
		model = Quiz
		fields = [
			'id',
			'course',
			'course_title',
			'title',
			'description',
			'pass_percentage',
			'max_attempts',
			'questions',
		]


class QuizAttemptSerializer(serializers.ModelSerializer):
	quiz_title = serializers.CharField(
		source='quiz.title',
		read_only=True
	)

	class Meta:
		model = QuizAttempt
		fields = [
			'id',
			'quiz',
			'quiz_title',
			'enrollment',
			'score',
			'percentage',
			'is_passed',
			'started_at',
			'completed_at',
		]
		read_only_fields = [
			'id',
			'quiz',
			'quiz_title',
			'enrollment',
			'score',
			'percentage',
			'is_passed',
			'started_at',
			'completed_at',
		]


class StudentAnswerSubmitSerializer(serializers.Serializer):
	question = serializers.IntegerField()
	selected_option = serializers.IntegerField()


class QuizSubmitSerializer(serializers.Serializer):
	answers = StudentAnswerSubmitSerializer(many=True)

	def validate_answers(self, value):
		if not value:
			raise serializers.ValidationError(
				'At least one answer is required.'
			)

		question_ids = [
			answer['question']
			for answer in value
		]

		if len(question_ids) != len(set(question_ids)):
			raise serializers.ValidationError(
				'Each question can only be answered once.'
			)

		return value


class InstructorQuizResultSerializer(serializers.ModelSerializer):
	student_id = serializers.IntegerField(
		source='student.id',
		read_only=True
	)

	student_name = serializers.CharField(
		source='student.name',
		read_only=True
	)

	student_email = serializers.EmailField(
		source='student.email',
		read_only=True
	)

	quiz_title = serializers.CharField(
		source='quiz.title',
		read_only=True
	)

	class Meta:
		model = QuizAttempt
		fields = [
			'id',
			'student_id',
			'student_name',
			'student_email',
			'quiz',
			'quiz_title',
			'score',
			'percentage',
			'is_passed',
			'started_at',
			'completed_at',
		]
		read_only_fields = fields


class LearningStreakSerializer(serializers.ModelSerializer):
	class Meta:
		model = LearningStreak
		fields = ['current_streak', 'longest_streak', 'last_active_date']


class LeaderboardEntrySerializer(serializers.Serializer):
	rank = serializers.IntegerField()
	student_id = serializers.IntegerField()
	student_name = serializers.CharField()
	current_streak = serializers.IntegerField()
	longest_streak = serializers.IntegerField()


class PointTransactionSerializer(serializers.ModelSerializer):
	class Meta:
		model = PointTransaction
		fields = [
			'id',
			'points',
			'event_type',
			'quiz_attempt',
			'question',
			'description',
			'created_at',
		]
		read_only_fields = fields


class PointsLeaderboardEntrySerializer(serializers.Serializer):
	rank = serializers.IntegerField()
	student_id = serializers.IntegerField()
	student_name = serializers.CharField()
	total_points = serializers.IntegerField()


class CertificateSerializer(serializers.ModelSerializer):
	course_title = serializers.CharField(source='course.title', read_only=True)
	grade_name = serializers.CharField(source='grade.name', read_only=True)

	class Meta:
		model = Certificate
		fields = ['id', 'certificate_type', 'course', 'course_title', 'grade', 'grade_name', 'issued_at']


class CertificateCriteriaSerializer(serializers.ModelSerializer):
	class Meta:
		model = CertificateCriteria
		fields = ['skill_course_requires_quiz_pass', 'academic_grade_min_completion_percentage']


class BadgeSerializer(serializers.ModelSerializer):
	class Meta:
		model = Badge
		fields = [
			'id',
			'name',
			'description',
			'icon_url',
			'criteria_type',
			'criteria_value',
			'is_active',
		]
		read_only_fields = ['id']

	def validate_criteria_value(self, value):
		if value < 1:
			raise serializers.ValidationError(
				'Criteria value must be at least 1.'
			)

		return value


class StudentBadgeSerializer(serializers.ModelSerializer):
	badge_id = serializers.IntegerField(source='badge.id', read_only=True)
	name = serializers.CharField(source='badge.name', read_only=True)
	description = serializers.CharField(source='badge.description', read_only=True)
	icon_url = serializers.CharField(source='badge.icon_url', read_only=True)
	criteria_type = serializers.CharField(source='badge.criteria_type', read_only=True)

	class Meta:
		model = StudentBadge
		fields = [
			'id',
			'badge_id',
			'name',
			'description',
			'icon_url',
			'criteria_type',
			'awarded_at',
		]


class ChallengeSerializer(serializers.ModelSerializer):
	subject_name = serializers.CharField(
		source='subject.name',
		read_only=True,
		allow_null=True
	)
	grade_name = serializers.CharField(
		source='grade.name',
		read_only=True,
		allow_null=True
	)
	created_by_name = serializers.CharField(
		source='created_by.name',
		read_only=True
	)
	participant_count = serializers.SerializerMethodField()
	is_ended = serializers.SerializerMethodField()
	winners = serializers.SerializerMethodField()
	my_status = serializers.SerializerMethodField()

	class Meta:
		model = Challenge
		fields = [
			'id',
			'title',
			'description',
			'subject',
			'subject_name',
			'grade',
			'grade_name',
			'points',
			'end_at',
			'is_ended',
			'is_published',
			'created_by',
			'created_by_name',
			'participant_count',
			'winners',
			'my_status',
			'created_at',
			'updated_at',
		]
		read_only_fields = [
			'id',
			'created_by',
			'created_at',
			'updated_at',
		]

	def get_participant_count(self, obj):
		count = getattr(obj, 'participant_count', None)

		if count is None:
			count = obj.participants.count()

		return count

	def get_is_ended(self, obj):
		return obj.end_at <= timezone.now()

	def get_winners(self, obj):
		winners = getattr(obj, 'winner_participants', None)

		if winners is None:
			winners = list(
				obj.participants.filter(
					is_winner=True
				).select_related('student')
			)

		return [
			{
				'participant_id': winner.id,
				'student_id': winner.student_id,
				'student_name': winner.student.name,
			}
			for winner in winners
		]

	def get_my_status(self, obj):
		statuses = self.context.get('my_statuses')

		if statuses is None:
			return None

		return statuses.get(obj.pk)

	def validate_end_at(self, value):
		now = timezone.now()

		if self.instance is not None:
			if value == self.instance.end_at:
				return value

			if self.instance.end_at <= now:
				raise serializers.ValidationError(
					'The end time cannot be changed after the challenge has ended.'
				)

		if value <= now:
			raise serializers.ValidationError(
				'The end time must be in the future.'
			)

		return value


class ChallengeParticipantSerializer(serializers.ModelSerializer):
	challenge_title = serializers.CharField(
		source='challenge.title',
		read_only=True
	)
	challenge_end_at = serializers.DateTimeField(
		source='challenge.end_at',
		read_only=True
	)
	student_id = serializers.IntegerField(
		source='student.id',
		read_only=True
	)
	student_name = serializers.CharField(
		source='student.name',
		read_only=True
	)
	student_email = serializers.EmailField(
		source='student.email',
		read_only=True
	)
	reviewed_by_name = serializers.CharField(
		source='reviewed_by.name',
		read_only=True,
		allow_null=True
	)

	class Meta:
		model = ChallengeParticipant
		fields = [
			'id',
			'challenge',
			'challenge_title',
			'challenge_end_at',
			'student_id',
			'student_name',
			'student_email',
			'status',
			'submission_text',
			'submission_url',
			'submitted_at',
			'reviewed_by_name',
			'reviewed_at',
			'points_awarded',
			'is_winner',
			'joined_at',
		]
		read_only_fields = fields


class ChallengeSubmitSerializer(serializers.Serializer):
	submission_text = serializers.CharField(
		required=False,
		allow_blank=True,
		max_length=2000
	)
	submission_url = serializers.URLField(
		required=False,
		allow_blank=True,
		max_length=500
	)

	def validate(self, attrs):
		text = attrs.get('submission_text', '').strip()
		url = attrs.get('submission_url', '').strip()

		if not text and not url:
			raise serializers.ValidationError({
				'detail': 'Provide a text answer or a link.'
			})

		attrs['submission_text'] = text
		attrs['submission_url'] = url

		return attrs


class ChallengeReviewSerializer(serializers.Serializer):
	action = serializers.ChoiceField(choices=['approve', 'reject'])


class ChallengeWinnersSerializer(serializers.Serializer):
	participants = serializers.ListField(
		child=serializers.IntegerField(),
		allow_empty=True
	)


class ShortCommentSerializer(serializers.ModelSerializer):
	student_id = serializers.IntegerField(
		source='student.id',
		read_only=True
	)

	student_name = serializers.CharField(
		source='student.name',
		read_only=True
	)

	class Meta:
		model = ShortComment
		fields = [
			'id',
			'short',
			'student_id',
			'student_name',
			'text',
			'created_at',
		]

		read_only_fields = [
			'id',
			'short',
			'student_id',
			'student_name',
			'created_at',
		]


class ShortSerializer(serializers.ModelSerializer):
	instructor_id = serializers.IntegerField(
		source='instructor.id',
		read_only=True
	)

	instructor_name = serializers.CharField(
		source='instructor.name',
		read_only=True
	)

	like_count = serializers.SerializerMethodField()
	comment_count = serializers.SerializerMethodField()
	is_liked = serializers.SerializerMethodField()
	is_saved = serializers.SerializerMethodField()

	class Meta:
		model = Short

		fields = [
			'id',
			'title',
			'instructor_id',
			'instructor_name',
			'video_url',
			'thumbnail_url',
			'is_published',
			'view_count',
			'like_count',
			'comment_count',
			'is_liked',
			'is_saved',
			'created_at',
			'updated_at',
		]

		read_only_fields = [
			'id',
			'instructor_id',
			'instructor_name',
			'view_count',
			'like_count',
			'comment_count',
			'is_liked',
			'is_saved',
			'created_at',
			'updated_at',
		]

	def get_is_saved(self, obj):
		request = self.context.get('request')
		if not request or not request.user.is_authenticated:
			return False
		if getattr(getattr(request.user, 'role', None), 'name', '') != 'student':
			return False
		return bool(getattr(obj, '_is_saved', False))

	def get_like_count(self, obj):
		return obj.likes.count()

	def get_comment_count(self, obj):
		return obj.comments.count()

	def get_is_liked(self, obj):
		request = self.context.get('request')

		if not request:
			return False

		if not request.user.is_authenticated:
			return False

		return obj.likes.filter(
			student=request.user
		).exists()

	def validate(self, attrs):
		attrs = super().validate(attrs)

		request = self.context.get('request')

		if not request:
			return attrs

		user = request.user

		role_name = getattr(
			getattr(user, 'role', None),
			'name',
			''
		)

		is_admin = (
			user.is_superuser
			or role_name == 'super_admin'
		)

		if (
			'is_published' in attrs
			and attrs['is_published']
			and not is_admin
			and (
				role_name != 'instructor'
				or user.verification_status != 'verified'
			)
		):
			raise serializers.ValidationError({
				'is_published': (
					'Only verified instructors '
					'can publish Shorts.'
				)
			})

		return attrs


class ShortViewSerializer(serializers.ModelSerializer):
	class Meta:
		model = ShortView

		fields = [
			'id',
			'student',
			'short',
			'viewed_at',
		]

		read_only_fields = [
			'id',
			'student',
			'short',
			'viewed_at',
		]


class ShortLikeSerializer(serializers.ModelSerializer):
	class Meta:
		model = ShortLike

		fields = [
			'id',
			'student',
			'short',
			'created_at',
		]

		read_only_fields = [
			'id',
			'student',
			'short',
			'created_at',
		]


class EBookSerializer(serializers.ModelSerializer):
	subject_name = serializers.CharField(
		source='subject.name',
		read_only=True,
		allow_null=True
	)
	grade_name = serializers.CharField(
		source='grade.name',
		read_only=True,
		allow_null=True
	)
	uploaded_by_name = serializers.CharField(
		source='uploaded_by.name',
		read_only=True
	)

	class Meta:
		model = EBook
		fields = [
			'id',
			'title',
			'description',
			'author',
			'subject',
			'subject_name',
			'grade',
			'grade_name',
			'uploaded_by',
			'uploaded_by_name',
			'cover_url',
			'file_url',
			'is_published',
			'created_at',
			'updated_at',
		]
		read_only_fields = [
			'id',
			'uploaded_by',
			'created_at',
			'updated_at',
		]


class NotificationSerializer(serializers.ModelSerializer):
	class Meta:
		model = Notification

		fields = [
			'id',
			'notification_type',
			'title',
			'message',
			'related_type',
			'related_id',
			'is_read',
			'read_at',
			'created_at',
		]

		read_only_fields = [
			'id',
			'notification_type',
			'title',
			'message',
			'related_type',
			'related_id',
			'is_read',
			'read_at',
			'created_at',
		]


# =========================================================
# Rewards & Redemption
# =========================================================


class RewardSerializer(serializers.ModelSerializer):
	available = serializers.SerializerMethodField()

	class Meta:
		model = Reward
		fields = [
			'id',
			'name',
			'description',
			'points_required',
			'stock',
			'is_active',
			'available',
			'created_at',
			'updated_at',
		]
		read_only_fields = [
			'id',
			'created_at',
			'updated_at',
		]

	def get_available(self, obj):
		return (
			obj.is_active
			and (obj.stock is None or obj.stock > 0)
		)


class AdminRewardSerializer(RewardSerializer):
	points_required = serializers.IntegerField(min_value=1, max_value=2147483647)
	stock = serializers.IntegerField(min_value=0, max_value=2147483647, allow_null=True, required=False)

	def validate(self, attrs):
		unknown = set(self.initial_data) - {'name', 'description', 'points_required', 'stock', 'is_active'}
		if unknown:
			raise serializers.ValidationError({field: 'This field cannot be supplied.' for field in sorted(unknown)})
		return attrs


class RedemptionTransitionSerializer(serializers.Serializer):
	status = serializers.ChoiceField(choices=Redemption.STATUS_CHOICES)
	note = serializers.CharField(required=False, allow_blank=True)

	def validate(self, attrs):
		unknown = set(self.initial_data) - {'status', 'note'}
		if unknown:
			raise serializers.ValidationError({field: 'This field cannot be supplied.' for field in sorted(unknown)})
		return attrs


class AdminRedemptionSerializer(serializers.ModelSerializer):
	reward = RewardSerializer(read_only=True)
	student = serializers.SerializerMethodField()

	class Meta:
		model = Redemption
		fields = ['id', 'student', 'reward', 'points_spent', 'status', 'note', 'created_at', 'updated_at']
		read_only_fields = fields

	def get_student(self, obj):
		return {'id': obj.student_id, 'name': obj.student.name}


class RedemptionSerializer(serializers.ModelSerializer):
	reward = RewardSerializer(read_only=True)

	reward_id = serializers.PrimaryKeyRelatedField(
		source='reward',
		queryset=Reward.objects.filter(is_active=True),
		write_only=True
	)

	class Meta:
		model = Redemption
		fields = [
			'id',
			'reward',
			'reward_id',
			'points_spent',
			'status',
			'note',
			'created_at',
			'updated_at',
		]
		read_only_fields = [
			'id',
			'points_spent',
			'status',
			'note',
			'created_at',
			'updated_at',
		]
