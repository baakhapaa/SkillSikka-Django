from django import forms

from .models import (
	CertificateCriteria,
	Course,
	District,
	Event,
	Grade,
	Municipality,
	Province,
	School,
	StreakSettings,
	User,
)


class ProvinceForm(forms.ModelForm):
	class Meta:
		model = Province
		fields = ['name']
		widgets = {
			'name': forms.TextInput(attrs={'placeholder': 'e.g. Bagmati'}),
		}


class DistrictForm(forms.ModelForm):
	class Meta:
		model = District
		fields = ['name', 'province']
		widgets = {
			'name': forms.TextInput(attrs={'placeholder': 'e.g. Kathmandu'}),
		}


class MunicipalityForm(forms.ModelForm):
	class Meta:
		model = Municipality
		fields = ['name', 'district']
		widgets = {
			'name': forms.TextInput(attrs={'placeholder': 'e.g. Kirtipur'}),
		}


class GradeForm(forms.ModelForm):
	class Meta:
		model = Grade
		fields = ['name']
		widgets = {
			'name': forms.TextInput(attrs={'placeholder': 'e.g. Grade 8'}),
		}


class SchoolForm(forms.ModelForm):
	class Meta:
		model = School
		fields = ['name', 'municipality', 'sector', 'logo_url']
		widgets = {
			'name': forms.TextInput(attrs={'placeholder': 'e.g. SkillSikka Academy'}),
			'logo_url': forms.URLInput(attrs={'placeholder': 'https://example.com/logo.png'}),
		}


class CourseForm(forms.ModelForm):
	instructor = forms.ModelChoiceField(
		queryset=User.objects.filter(role__name='instructor').order_by('name'),
	)

	class Meta:
		model = Course
		fields = [
			'title', 'description', 'instructor', 'course_type',
			'subject', 'grade', 'is_paid', 'price', 'thumbnail_url', 'is_published',
		]
		widgets = {
			'title': forms.TextInput(attrs={'placeholder': 'e.g. Intro to Python'}),
			'thumbnail_url': forms.URLInput(attrs={'placeholder': 'https://example.com/thumbnail.png'}),
		}


class StreakSettingsForm(forms.ModelForm):
	class Meta:
		model = StreakSettings
		fields = ['grace_period_days']


class CertificateCriteriaForm(forms.ModelForm):
	class Meta:
		model = CertificateCriteria
		fields = ['skill_course_requires_quiz_pass', 'academic_grade_min_completion_percentage']


class UserAdminForm(forms.ModelForm):
	class Meta:
		model = User
		fields = ['name', 'phone_country_code', 'phone_number', 'gender', 'dob', 'location']
		widgets = {
			'dob': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
		}


class MunicipalityChoiceField(forms.ModelChoiceField):
	def label_from_instance(self, municipality):
		return f'{municipality.name} ({municipality.district.name})'


class EventForm(forms.ModelForm):
	"""Times are entered and shown in the active timezone (the view sets NPT)."""

	host = forms.ModelChoiceField(
		queryset=User.objects.filter(role__name='instructor', is_active=True).order_by('name'),
		required=False,
		help_text='Instructor shown as the host.',
	)
	district = forms.ModelChoiceField(
		queryset=District.objects.order_by('name'),
		required=False,
		help_text='Required for in-person and hybrid events.',
	)
	municipality = MunicipalityChoiceField(
		queryset=Municipality.objects.select_related('district').order_by('name'),
		required=False,
		help_text='Optional. The district is filled in from it.',
	)
	highlights = forms.CharField(
		required=False,
		widget=forms.Textarea(attrs={'rows': 4, 'placeholder': 'One point per line'}),
		help_text='"What you\'ll learn": one point per line, up to 10.',
	)
	start_at = forms.DateTimeField(
		input_formats=['%Y-%m-%dT%H:%M'],
		widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
		label='Starts (Nepal time)',
	)
	end_at = forms.DateTimeField(
		input_formats=['%Y-%m-%dT%H:%M'],
		widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
		label='Ends (Nepal time)',
	)

	class Meta:
		model = Event
		fields = [
			'title', 'description', 'highlights', 'cover_image',
			'host', 'host_role', 'start_at', 'end_at', 'format',
			'venue_name', 'city', 'district', 'municipality',
			'latitude', 'longitude', 'capacity', 'is_published',
		]
		labels = {
			'host_role': 'Host subtitle',
			'is_published': 'Published (visible in the app)',
		}
		help_texts = {
			'host_role': 'e.g. "Mathematics Dept Head". Defaults to "Instructor".',
			'capacity': 'Leave empty for unlimited. When full, new sign-ups join a waitlist.',
			'latitude': 'Optional, e.g. 27.7172. Enables distance-based "near you".',
			'longitude': 'Optional, e.g. 85.3240.',
		}
		widgets = {
			'title': forms.TextInput(attrs={'placeholder': 'e.g. Advanced Algebra Masterclass'}),
			'description': forms.Textarea(attrs={'rows': 4}),
			'venue_name': forms.TextInput(attrs={'placeholder': 'e.g. Seminar Hall A, Tech Hub'}),
			'city': forms.TextInput(attrs={'placeholder': 'e.g. Kathmandu, Nepal'}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.instance.pk and not self.is_bound:
			self.initial['highlights'] = '\n'.join(self.instance.highlights or [])

	def clean_highlights(self):
		lines = [line.strip() for line in self.cleaned_data['highlights'].splitlines() if line.strip()]
		if len(lines) > 10:
			raise forms.ValidationError('Use at most 10 points.')
		if any(len(line) > 200 for line in lines):
			raise forms.ValidationError('Each point must be at most 200 characters.')
		return lines

	def clean_cover_image(self):
		from rest_framework import serializers

		from .advertisement_serializers import validate_banner_image

		upload = self.cleaned_data.get('cover_image')
		if upload and hasattr(upload, 'content_type'):  # a new upload, not the stored file
			try:
				validate_banner_image(upload)
			except serializers.ValidationError as exc:
				raise forms.ValidationError(exc.detail)
		return upload

	def clean_capacity(self):
		capacity = self.cleaned_data.get('capacity')
		if capacity is not None and capacity < 1:
			raise forms.ValidationError('Capacity must be at least 1, or empty for unlimited.')
		return capacity

	def clean(self):
		cleaned = super().clean()
		start_at, end_at = cleaned.get('start_at'), cleaned.get('end_at')
		if start_at and end_at and end_at < start_at:
			self.add_error('end_at', 'End time must not be earlier than start time.')

		latitude, longitude = cleaned.get('latitude'), cleaned.get('longitude')
		if (latitude is None) != (longitude is None):
			self.add_error('latitude', 'Enter latitude and longitude together, or neither.')
		if latitude is not None and not -90 <= latitude <= 90:
			self.add_error('latitude', 'Latitude must be between -90 and 90.')
		if longitude is not None and not -180 <= longitude <= 180:
			self.add_error('longitude', 'Longitude must be between -180 and 180.')

		district, municipality = cleaned.get('district'), cleaned.get('municipality')
		if municipality is not None:
			if district is None:
				district = cleaned['district'] = municipality.district
			elif municipality.district_id != district.pk:
				self.add_error('municipality', 'This municipality is not in the selected district.')

		if cleaned.get('format') in ('in_person', 'hybrid') and district is None:
			self.add_error('district', 'In-person and hybrid events need a district.')

		self.instance.province = district.province if district else None
		return cleaned