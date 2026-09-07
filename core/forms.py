from django import forms

from .models import District, Grade, Municipality, Province, School


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
