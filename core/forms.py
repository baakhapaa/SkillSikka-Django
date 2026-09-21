from django import forms

from .models import (
	CertificateCriteria,
	Course,
	District,
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