from django import forms
from decimal import Decimal
from django.db import transaction

from .models import (
	BootcampProfile,
	CertificateCriteria,
	Course,
	CourseInstructor,
	CourseResource,
	District,
	Event,
	Grade,
	Lesson,
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
	# This legacy form cannot submit the required profile and instructor roster.
	course_type = forms.ChoiceField(choices=[choice for choice in Course.COURSE_TYPE_CHOICES if choice[0] != 'bootcamp'])

	instructor = forms.ModelChoiceField(
		queryset=User.objects.filter(role__name='instructor').order_by('name'),
	)

	class Meta:
		model = Course
		fields = [
			'title', 'description', 'instructor', 'course_type',
			'skill_category',
			'learning_outcomes', 'requirements',
			'subject', 'grade', 'is_paid', 'price', 'thumbnail_url', 'is_published',
		]
		widgets = {
			'title': forms.TextInput(attrs={'placeholder': 'e.g. Intro to Python'}),
			'thumbnail_url': forms.URLInput(attrs={'placeholder': 'https://example.com/thumbnail.png'}),
		}

	def clean(self):
		# Same rule as the course API: checkout needs a price on paid courses.
		cleaned = super().clean()
		from .serializers import CourseStringList
		from rest_framework.exceptions import ValidationError
		for field in ['learning_outcomes', 'requirements']:
			if field in cleaned:
				try:
					value = cleaned[field]
					cleaned[field] = CourseStringList().run_validation([] if value is None else value)
				except ValidationError:
					self.add_error(field, 'Use a list of non-empty strings, each at most 500 characters.')
		if cleaned.get('is_paid'):
			price = cleaned.get('price')
			if price is None or price <= 0:
				self.add_error('price', 'A paid course must have a price greater than 0.')
		else:
			cleaned['price'] = None
		return cleaned


class BootcampForm(forms.Form):
	"""Create an ICT & AI bootcamp from the dashboard.

	**Bootcamps are admin-only, and this is the only door.** The API enforces
	the same rule (`require_bootcamp_admin`), `CourseForm` above deliberately
	omits the type, and the app's builder (`CourseKind`) has no bootcamp member,
	so neither an instructor nor a student has a path to create one.

	**Not a `ModelForm`, because one bootcamp is three rows** — the course, its
	[BootcampProfile] and the [CourseInstructor] roster — and a `ModelForm` saves
	one. [save] writes all three in a single transaction so a rejected profile
	cannot leave a half-built course behind.

	Free remains the default; paid bootcamps use the existing Course price rules.
	"""

	title = forms.CharField(
		max_length=200,
		widget=forms.TextInput(attrs={'placeholder': 'ICT & AI BOOTCAMP at Sundarbazar'}),
	)
	description = forms.CharField(
		required=False,
		widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'What the camp covers.'}),
	)
	short_description = forms.CharField(
		required=False,
		max_length=300,
		label='Short description',
		widget=forms.TextInput(attrs={'placeholder': 'The two-line lede under the title.'}),
	)
	instructor = forms.ModelChoiceField(
		queryset=User.objects.filter(role__name='instructor').order_by('name'),
		label='Lead instructor',
	)
	coaches = forms.ModelMultipleChoiceField(
		queryset=User.objects.filter(role__name='instructor').order_by('name'),
		required=False,
		label='Coaches',
		help_text='Everyone else on the roster. The lead is added automatically.',
		widget=forms.SelectMultiple(attrs={'size': 6}),
	)
	venue_name = forms.CharField(
		max_length=150,
		label='Venue',
		widget=forms.TextInput(attrs={'placeholder': 'Sundarbazar'}),
	)
	days = forms.IntegerField(min_value=1, max_value=30, initial=4)
	starts_on = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
	ends_on = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
	status = forms.ChoiceField(
		choices=BootcampProfile.STATUS_CHOICES,
		initial='upcoming',
	)
	episode_no = forms.IntegerField(
		required=False,
		min_value=1,
		label='Episode',
		help_text='The pill beside Discussions. Leave blank if this is not an episode.',
	)
	quality_label = forms.CharField(
		required=False,
		max_length=8,
		label='Quality tag',
		widget=forms.TextInput(attrs={'placeholder': 'HD'}),
	)
	hero_video_url = forms.URLField(
		required=False,
		label='Hero video URL',
		widget=forms.URLInput(attrs={'placeholder': 'https://.../episode.mp4'}),
	)
	hero_poster_url = forms.URLField(
		required=False,
		label='Hero poster URL',
		widget=forms.URLInput(attrs={'placeholder': 'https://.../poster.jpg'}),
	)
	thumbnail_url = forms.URLField(
		required=False,
		label='Card image URL',
		widget=forms.URLInput(attrs={'placeholder': 'https://.../card.png'}),
	)
	level = forms.ChoiceField(
		choices=[('', '—')] + list(Course.LEVEL_CHOICES),
		required=False,
	)
	language = forms.CharField(required=False, max_length=50, initial='English')
	is_paid = forms.BooleanField(required=False, label='Paid bootcamp')
	price = forms.DecimalField(required=False, max_digits=8, decimal_places=2, min_value=Decimal('0.01'))
	is_published = forms.BooleanField(
		required=False,
		initial=True,
		label='Publish now',
		help_text='Unpublished bootcamps are invisible to students.',
	)

	def __init__(self, *args, instance=None, **kwargs):
		"""Prefill from an existing camp when [instance] is given.

		The same form adds and edits: the fields are identical, and a separate
		edit form would be a second place for `days`, the roster and the dates to
		drift apart. `instance` is the `Course`; its profile supplies the rest.
		"""
		self.instance = instance
		super().__init__(*args, **kwargs)
		if instance is None:
			return
		profile = getattr(instance, 'bootcamp_profile', None)
		self.initial.update({
			'title': instance.title,
			'description': instance.description,
			'short_description': getattr(profile, 'short_description', ''),
			'instructor': instance.instructor_id,
			'coaches': list(
				instance.instructors
				.exclude(instructor_id=instance.instructor_id)
				.values_list('instructor_id', flat=True)
			),
			'venue_name': getattr(profile, 'venue_name', ''),
			'days': getattr(profile, 'days', 1),
			'starts_on': getattr(profile, 'starts_on', None),
			'ends_on': getattr(profile, 'ends_on', None),
			'status': getattr(profile, 'status', 'upcoming'),
			'episode_no': getattr(profile, 'episode_no', None),
			'quality_label': getattr(profile, 'quality_label', ''),
			'hero_video_url': getattr(profile, 'hero_video_url', ''),
			'hero_poster_url': getattr(profile, 'hero_poster_url', ''),
			'thumbnail_url': instance.thumbnail_url,
			'level': instance.level,
			'language': instance.language,
			'is_paid': instance.is_paid,
			'price': instance.price,
			'is_published': instance.is_published,
		})

	def clean(self):
		cleaned = super().clean()
		start = cleaned.get('starts_on')
		end = cleaned.get('ends_on')
		if start and end and end < start:
			# Same rule as `BootcampProfile.clean()`; caught here so the admin
			# sees the message on the field instead of a 500 from the model.
			self.add_error('ends_on', 'End date must not precede start date.')
		if cleaned.get('is_paid') and not cleaned.get('price'):
			self.add_error('price', 'A paid bootcamp must have a price greater than 0.')
		if not cleaned.get('is_paid'):
			cleaned['price'] = None
		lead = cleaned.get('instructor')
		coaches = cleaned.get('coaches')
		if lead and coaches and lead in coaches:
			# The roster is unique per instructor, so saving the lead twice would
			# hit `unique_course_instructor` and 500 after the course exists.
			self.add_error('coaches', 'The lead instructor is already on the roster.')
		days = cleaned.get('days')
		if self.instance is not None and days:
			# Same rule as the API: shortening the camp under a lesson's day would
			# leave that lesson on a tab the app never draws.
			if self.instance.lessons.filter(day_number__gt=days).exists():
				self.add_error('days', 'Existing lessons exceed the proposed days.')
		return cleaned

	@transaction.atomic
	def save(self):
		data = self.cleaned_data
		course = self.instance
		if course is None:
			course = Course.objects.create(
				title=data['title'],
				description=data.get('description') or '',
				instructor=data['instructor'],
				course_type='bootcamp',
				level=data.get('level') or '',
				language=data.get('language') or 'English',
				is_paid=data.get('is_paid', False),
				price=data.get('price'),
				thumbnail_url=data.get('thumbnail_url') or '',
				is_published=data.get('is_published', False),
			)
		else:
			course.title = data['title']
			course.description = data.get('description') or ''
			course.instructor = data['instructor']
			course.level = data.get('level') or ''
			course.language = data.get('language') or 'English'
			course.thumbnail_url = data.get('thumbnail_url') or ''
			course.is_published = data.get('is_published', False)
			course.is_paid = data.get('is_paid', False)
			course.price = data.get('price')
			course.save()
		BootcampProfile.objects.update_or_create(
			course=course,
			defaults={
				'venue_name': data['venue_name'],
				'days': data['days'],
				'starts_on': data['starts_on'],
				'ends_on': data['ends_on'],
				'status': data['status'],
				'episode_no': data.get('episode_no'),
				'short_description': data.get('short_description') or '',
				'hero_video_url': data.get('hero_video_url') or '',
				'hero_poster_url': data.get('hero_poster_url') or '',
				'quality_label': data.get('quality_label') or '',
			},
		)
		# Remove deselected members while preserving retained coach/guest roles.
		_save_bootcamp_roster(course, data['instructor'], data.get('coaches'))
		# The instance came in with `select_related('bootcamp_profile')`, so its
		# cached profile is the pre-update one. Same clear as
		# `CourseSerializer.update`, and for the same reason: the next read of
		# `course.bootcamp_profile` must hit the row we just wrote.
		course._state.fields_cache.pop('bootcamp_profile', None)
		course._prefetched_objects_cache = {}
		return course


def _save_bootcamp_roster(course, lead, coaches):
	"""Replace membership while retaining existing coach/guest roles."""
	coaches = list(coaches or [])
	course.instructors.exclude(instructor__in=[lead, *coaches]).delete()
	CourseInstructor.objects.update_or_create(course=course, instructor=lead, defaults={'role': 'lead', 'order': 0})
	for index, coach in enumerate(coaches, start=1):
		row, created = CourseInstructor.objects.get_or_create(
			course=course, instructor=coach, defaults={'role': 'coach', 'order': index})
		if not created and row.role == 'lead':
			row.role, row.order = 'coach', index
			row.save(update_fields=['role', 'order'])


class BootcampInstructorForm(forms.Form):
	instructor = forms.ModelChoiceField(queryset=User.objects.filter(
		role__name='instructor', is_active=True, verification_status='verified'), label='Lead instructor')
	coaches = forms.ModelMultipleChoiceField(queryset=User.objects.filter(
		role__name='instructor', is_active=True, verification_status='verified'), required=False,
		label='Other instructors', help_text='Existing coach/guest roles are retained. New members join as coaches.')

	def __init__(self, *args, instance, **kwargs):
		self.instance = instance
		super().__init__(*args, **kwargs)
		self.initial.update(instructor=instance.instructor_id,
			coaches=list(instance.instructors.exclude(instructor=instance.instructor).values_list('instructor_id', flat=True)))

	def clean(self):
		data = super().clean()
		if data.get('instructor') and data.get('coaches') and data['instructor'] in data['coaches']:
			self.add_error('coaches', 'The lead instructor is already on the roster.')
		return data

	@transaction.atomic
	def save(self):
		self.instance.instructor = self.cleaned_data['instructor']
		self.instance.save(update_fields=['instructor'])
		_save_bootcamp_roster(self.instance, self.instance.instructor, self.cleaned_data.get('coaches'))
		return self.instance


class BootcampUploadForm(forms.Form):
	"""Use the existing course asset upload limits and storage path."""
	def clean_upload(self, field, kind):
		from .api_views import CourseAssetUploadAPIView
		upload = self.cleaned_data.get(field)
		if upload:
			policy = CourseAssetUploadAPIView
			allowed = policy.LESSON_TYPES if kind == 'lesson' else policy.RESOURCE_TYPES
			limit = policy.LESSON_MAX_BYTES if kind == 'lesson' else policy.RESOURCE_MAX_BYTES
			if upload.content_type.lower() not in allowed:
				raise forms.ValidationError('This file type is not supported.')
			if upload.size > limit:
				raise forms.ValidationError(f'That file is larger than {limit // (1024 * 1024)} MB.')
		return upload

	def store_upload(self, field, kind, course, request):
		from .api_views import CourseAssetUploadAPIView
		return CourseAssetUploadAPIView()._store(self.cleaned_data[field], kind, course, request)['url']


class BootcampLessonForm(BootcampUploadForm):
	"""One lesson on a bootcamp's Day tab.

	`day_number` is what the app groups by; it must sit inside the profile's
	`days` (the API enforces the same range, see `LessonSerializer.validate`).
	"""

	day_number = forms.IntegerField(min_value=1, label='Day')
	section = forms.CharField(
		required=False,
		max_length=200,
		widget=forms.TextInput(attrs={'placeholder': 'Section 1: Research & Strategy'}),
	)
	title = forms.CharField(
		max_length=200,
		widget=forms.TextInput(attrs={'placeholder': 'Defining the Product Strategy Grid'}),
	)
	duration = forms.CharField(
		required=False,
		label='Duration',
		help_text='mm:ss, e.g. 18:45.',
		widget=forms.TextInput(attrs={'placeholder': '18:45'}),
	)
	content_type = forms.ChoiceField(
		choices=Lesson.CONTENT_TYPE_CHOICES,
		initial='video',
		label='Kind',
	)
	content_url = forms.URLField(
		required=False,
		label='Content URL',
		widget=forms.URLInput(attrs={'placeholder': 'https://.../lesson.mp4'}),
	)
	content_text = forms.CharField(
		required=False,
		label='Description / text body',
		widget=forms.Textarea(attrs={'rows': 3}),
	)
	content_file = forms.FileField(required=False, label='Upload video / PDF / ebook')
	is_preview = forms.BooleanField(
		required=False,
		label='Free preview',
		help_text='Watchable without enrolling.',
	)
	order = forms.IntegerField(
		required=False,
		min_value=0,
		max_value=32767,
		help_text='Leave blank to append to the day.',
	)

	def __init__(self, *args, bootcamp=None, instance=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.bootcamp = bootcamp
		self.instance = instance
		if bootcamp and getattr(bootcamp, 'bootcamp_profile', None):
			self.fields['day_number'].widget = forms.Select(choices=[(day, f'Day {day}') for day in range(1, bootcamp.bootcamp_profile.days + 1)])
		if instance:
			self.initial.update({key: getattr(instance, key) for key in [
				'day_number', 'section', 'title', 'content_type', 'content_url', 'content_text', 'is_preview', 'order']})
			seconds = instance.duration_seconds
			self.initial['duration'] = f'{seconds // 60}:{seconds % 60:02}' if seconds is not None else ''

	def clean_content_file(self):
		return self.clean_upload('content_file', 'lesson')

	def clean_duration(self):
		return parse_duration(self.cleaned_data.get('duration'))

	def clean(self):
		cleaned = super().clean()
		day = cleaned.get('day_number')
		profile = getattr(self.bootcamp, 'bootcamp_profile', None) if self.bootcamp else None
		if day and profile and day > profile.days:
			self.add_error('day_number', f'This bootcamp runs {profile.days} days.')
		kind = cleaned.get('content_type')
		if kind == 'text' and not (cleaned.get('content_text') or '').strip():
			self.add_error('content_text', 'Text content is required for a text lesson.')
		upload = cleaned.get('content_file')
		if upload:
			expected = {'video': {'video/mp4', 'video/quicktime', 'video/x-m4v'},
				'pdf': {'application/pdf'}, 'ebook': {'application/epub+zip'}}
			if upload.content_type.lower() not in expected.get(kind, set()):
				self.add_error('content_file', 'The file must match the selected content kind.')
		if kind != 'text' and not cleaned.get('content_url') and not upload:
			self.add_error('content_url', 'A content URL is required for this lesson type.')
		return cleaned

	def save(self, course, request=None):
		data = self.cleaned_data
		order = data.get('order')
		if order is None:
			last = Lesson.objects.filter(course=course).order_by('-order').values_list('order', flat=True).first()
			order = (last or 0) + 1
		if data.get('content_file'):
			data['content_url'] = self.store_upload('content_file', 'lesson', course, request)
		lesson = self.instance or Lesson(course=course)
		values = dict(
			course=course,
			title=data['title'],
			section=(data.get('section') or '').strip() or None,
			day_number=data['day_number'],
			duration_seconds=data.get('duration'),
			content_type=data['content_type'],
			content_url=data.get('content_url') or '',
			content_text=data.get('content_text') or '',
			is_preview=data.get('is_preview', False),
			order=order,
		)
		for key, value in values.items():
			setattr(lesson, key, value)
		lesson.save()
		return lesson


class BootcampResourceForm(BootcampUploadForm):
	"""One file on the bootcamp's Resources tab, optionally tied to a lesson."""

	section = forms.CharField(
		required=False,
		max_length=200,
		widget=forms.TextInput(attrs={'placeholder': 'Section 1: Course Materials'}),
	)
	title = forms.CharField(
		max_length=200,
		widget=forms.TextInput(attrs={'placeholder': 'Product Strategy Grid Template'}),
	)
	file_format = forms.ChoiceField(
		choices=CourseResource.FORMAT_CHOICES,
		initial='pdf',
		label='Format',
	)
	file_url = forms.URLField(
		required=False,
		label='File URL',
		widget=forms.URLInput(attrs={'placeholder': 'https://.../template.pdf'}),
	)
	resource_file = forms.FileField(required=False, label='Upload resource')
	lesson = forms.ModelChoiceField(
		queryset=Lesson.objects.none(),
		required=False,
		label='Lesson',
		help_text='Leave blank for a course-wide file.',
	)
	order = forms.IntegerField(required=False, min_value=0, max_value=32767)

	def __init__(self, *args, bootcamp=None, instance=None, **kwargs):
		super().__init__(*args, **kwargs)
		self.instance = instance
		if instance:
			self.initial.update({key: getattr(instance, key) for key in ['section', 'title', 'file_format', 'file_url', 'lesson', 'order']})
		if bootcamp is not None:
			self.fields['lesson'].queryset = Lesson.objects.filter(course=bootcamp).order_by('day_number', 'order', 'pk')

	def clean_resource_file(self):
		return self.clean_upload('resource_file', 'resource')

	def clean(self):
		data = super().clean()
		if not data.get('file_url') and not data.get('resource_file'):
			self.add_error('file_url', 'Provide a file URL or upload a resource.')
		return data

	def save(self, course, request=None):
		data = self.cleaned_data
		if data.get('resource_file'):
			data['file_url'] = self.store_upload('resource_file', 'resource', course, request)
		resource = self.instance or CourseResource(course=course)
		values = dict(
			course=course,
			lesson=data.get('lesson'),
			section=(data.get('section') or '').strip(),
			title=data['title'],
			file_format=data['file_format'],
			file_url=data['file_url'],
			order=data.get('order') or 0,
		)
		for key, value in values.items():
			setattr(resource, key, value)
		if data.get('resource_file'):
			resource.file_size_bytes = data['resource_file'].size
		resource.save()
		return resource


def parse_duration(value):
	"""`18:45` → 1125 seconds; blank → None; junk → a field error.

	The design prints `mm:ss`, and the API stores seconds, so the conversion
	lives here rather than asking an admin to multiply by sixty.
	"""
	text = (value or '').strip()
	if not text:
		return None
	parts = text.split(':')
	if len(parts) > 3:
		raise forms.ValidationError('Use mm:ss or hh:mm:ss.')
	try:
		numbers = [int(part) for part in parts]
	except ValueError:
		raise forms.ValidationError('Use mm:ss or hh:mm:ss.')
	if any(number < 0 for number in numbers):
		raise forms.ValidationError('Duration cannot be negative.')
	if len(numbers) >= 2 and numbers[-1] >= 60:
		raise forms.ValidationError('Seconds must be below 60.')
	if len(numbers) == 3 and numbers[-2] >= 60:
		raise forms.ValidationError('Minutes must be below 60.')
	if len(numbers) == 1:
		return numbers[0]
	if len(numbers) == 2:
		return numbers[0] * 60 + numbers[1]
	return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


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
