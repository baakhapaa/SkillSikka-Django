from pathlib import Path

from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.text import slugify
from rest_framework import serializers

from .models import (
	District,
	Grade,
	InstructorProfile,
	Municipality,
	Province,
	School,
	StudentProfile,
	User,
	VerificationDocument,
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
	municipality_id = serializers.IntegerField(source='municipality.id', read_only=True)

	class Meta:
		model = School
		fields = ['id', 'name', 'logo_url', 'sector', 'municipality_id']


class GradeSerializer(LocationSerializer):
	class Meta(LocationSerializer.Meta):
		model = Grade


class RegistrationSerializer(serializers.Serializer):
	email = serializers.EmailField()
	password = serializers.CharField(write_only=True, min_length=8)
	confirm_password = serializers.CharField(write_only=True, min_length=8)
	name = serializers.CharField(max_length=150)
	gender = serializers.CharField(max_length=10)
	dob = serializers.DateField(input_formats=['%d/%m/%Y', '%Y-%m-%d'])
	phone_country_code = serializers.CharField(max_length=8)
	phone_number = serializers.CharField(max_length=30)
	location = serializers.CharField(max_length=255)
	province_id = serializers.PrimaryKeyRelatedField(queryset=Province.objects.all(), source='province')
	district_id = serializers.PrimaryKeyRelatedField(queryset=District.objects.select_related('province').all(), source='district')
	municipality_id = serializers.PrimaryKeyRelatedField(
		queryset=Municipality.objects.select_related('district').all(), source='municipality',
	)
	school_id = serializers.PrimaryKeyRelatedField(
		queryset=School.objects.select_related('municipality__district').all(),
		source='school',
		required=False,
		allow_null=True,
	)
	profile_photo = serializers.FileField(required=False, allow_null=True, write_only=True)

	def validate_email(self, value):
		if User.objects.filter(email__iexact=value).exists():
			raise serializers.ValidationError('A user with this email already exists.')
		return value

	def validate(self, attrs):
		if attrs['password'] != attrs.pop('confirm_password'):
			raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
		province = attrs['province']
		district = attrs['district']
		if district.province_id != province.id:
			raise serializers.ValidationError({'district_id': 'District does not belong to the selected province.'})
		municipality = attrs['municipality']
		if municipality.district_id != district.id:
			raise serializers.ValidationError({'municipality_id': 'Municipality does not belong to the selected district.'})
		school = attrs.get('school')
		if school and school.municipality_id != municipality.id:
			raise serializers.ValidationError({'school_id': 'School does not belong to the selected municipality.'})
		return attrs

	def _save_upload(self, uploaded_file, folder, user_id):
		filename = f'{folder}/{user_id}/{slugify(Path(uploaded_file.name).stem)}{Path(uploaded_file.name).suffix.lower()}'
		return default_storage.url(default_storage.save(filename, uploaded_file))

	def _create_user(self, validated_data, role_name):
		profile_photo = validated_data.pop('profile_photo', None)
		validated_data.pop('confirm_password', None)
		password = validated_data.pop('password')
		province = validated_data.pop('province')
		district = validated_data.pop('district')
		municipality = validated_data.pop('municipality')
		school = validated_data.pop('school', None)
		user = User(email=validated_data.pop('email'), **validated_data)
		user.set_password(password)
		user.role = user_role(role_name)
		user.onboarding_completed = True
		user.verification_status = 'pending'
		user.save()
		if profile_photo:
			user.profile_photo_url = self._save_upload(profile_photo, 'profile-photos', user.pk)
			user.save(update_fields=['profile_photo_url', 'updated_at'])
		return user, province, district, municipality, school

	def validate(self, attrs):
		attrs = super().validate(attrs)
		if not attrs.get('province') or not attrs.get('district'):
			raise serializers.ValidationError('Province and district are required for registration.')
		return attrs


class StudentRegistrationSerializer(RegistrationSerializer):
	grade_id = serializers.PrimaryKeyRelatedField(queryset=Grade.objects.all(), source='grade')
	student_id_card = serializers.FileField(required=False, allow_null=True, write_only=True)

	@transaction.atomic
	def create(self, validated_data):
		student_id_card = validated_data.pop('student_id_card', None)
		grade = validated_data.pop('grade')
		user, province, district, municipality, school = self._create_user(validated_data, 'student')
		profile = StudentProfile.objects.create(
			user=user,
			grade=grade,
			province=province,
			district=district,
			municipality=municipality,
			school=school,
		)
		if student_id_card:
			document = VerificationDocument.objects.create(
			user=user,
			document_type='student_id_card',
			file_url=self._save_upload(student_id_card, 'verification-documents', user.pk),
		)
			profile.student_id_card_document = document
			profile.save(update_fields=['student_id_card_document'])
		return user


class InstructorRegistrationSerializer(RegistrationSerializer):
	qualification = serializers.CharField(max_length=255)
	subject_expertise = serializers.CharField()
	experience_years = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0)
	cv_resume = serializers.FileField(required=False, allow_null=True, write_only=True)
	certificates_and_recommendations = serializers.ListField(
		child=serializers.FileField(), required=False, write_only=True,
	)

	@transaction.atomic
	def create(self, validated_data):
		cv_resume = validated_data.pop('cv_resume', None)
		documents = validated_data.pop('certificates_and_recommendations', [])
		qualification = validated_data.pop('qualification')
		subject_expertise = validated_data.pop('subject_expertise')
		experience_years = validated_data.pop('experience_years')

		user, province, district, municipality, school = self._create_user(
			validated_data,
			'instructor'
		)

		InstructorProfile.objects.create(
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
			VerificationDocument.objects.create(
				user=user,
				document_type='cv_resume',
				file_url=self._save_upload(
					cv_resume,
					'verification-documents',
					user.pk
				),
			)

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

		return user


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

		attrs['user'] = user
		return attrs


def user_role(role_name):
	from .models import Role
	return Role.objects.get(name=role_name)