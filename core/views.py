from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (
	BannerForm,
	BootcampForm,
	BootcampInstructorForm,
	BootcampLessonForm,
	BootcampResourceForm,
	CertificateCriteriaForm,
	CourseForm,
	DistrictForm,
	EventForm,
	EBookForm,
	BookChapterForm,
	GradeForm,
	MunicipalityForm,
	ProvinceForm,
	SchoolForm,
	StreakSettingsForm,
	UserAdminForm,
)
from .models import (
	Advertisement,
	Event,
	EBook,
	BookChapter,
	Payment,
	AdminAuditLog,
	CertificateCriteria,
	Course,
	CourseResource,
	District,
	Grade,
	Lesson,
	Municipality,
	Province,
	Role,
	School,
	StreakSettings,
	User,
	VerificationDocument,
)
from .documents import document_file_response
from .payments import GatewayError, refresh_payment


def login_view(request):
	if request.user.is_authenticated:
		return redirect('dashboard')
	if request.method == 'POST':
		email = request.POST.get('email', '').strip()
		password = request.POST.get('password', '')
		user = authenticate(request, username=email, password=password)
		if user is None:
			inactive_user = User.objects.filter(email__iexact=email, is_active=False).first()
			if inactive_user is not None and inactive_user.check_password(password):
				messages.error(request, 'This account is inactive. Contact an administrator.')
			else:
				messages.error(request, 'The email or password is incorrect.')
		elif user.role.name in ('student', 'instructor') and not user.email_verified:
			messages.warning(request, 'Verify your email before signing in.')
		elif not user.onboarding_completed:
			messages.warning(request, 'Complete onboarding before signing in.')
		elif not user.is_active:
			messages.error(request, 'This account is inactive. Contact an administrator.')
		else:
			login(request, user)
			return redirect('dashboard')
	return render(request, 'auth/login.html')


@login_required
def dashboard(request):
	if not is_admin(request.user):
		logout(request)
		messages.error(request, 'The dashboard is available to administrators only.')
		return redirect('login')

	users = User.objects.select_related('role').order_by('-created_at')
	stats = {
		'total_users': users.count(),
		'pending_reviews': users.filter(verification_status='pending').count(),
		'active_users': users.filter(is_active=True).count(),
	}
	return render(request, 'admin/dashboard.html', {'users': users[:8], 'stats': stats})


@login_required
def manage_geography(request):
	if not (request.user.is_superuser or getattr(request.user.role, 'name', '') == 'super_admin'):
		messages.error(request, 'You do not have permission to manage locations and grades.')
		return redirect('dashboard')

	forms = {
		'province': ProvinceForm(prefix='province'),
		'district': DistrictForm(prefix='district'),
		'municipality': MunicipalityForm(prefix='municipality'),
		'grade': GradeForm(prefix='grade'),
		'school': SchoolForm(prefix='school'),
	}
	if request.method == 'POST':
		form_type = request.POST.get('form_type')
		form = forms.get(form_type)
		if form is None:
			messages.error(request, 'Choose a valid record type.')
		else:
			form = form.__class__(request.POST, prefix=form_type)
			forms[form_type] = form
			if form.is_valid():
				record = form.save()
				messages.success(request, f'{record.__class__.__name__} "{record.name}" added successfully.')
				return redirect('manage_geography')

	return render(request, 'admin/geography.html', {
		'forms': forms,
		'provinces': Province.objects.order_by('name'),
		'districts': District.objects.select_related('province').order_by('province__name', 'name'),
		'municipalities': Municipality.objects.select_related('district__province').order_by('district__province__name', 'district__name', 'name'),
		'grades': Grade.objects.order_by('name'),
		'schools': School.objects.select_related('municipality__district__province').order_by('name'),
	})


def is_admin(user):
	return user.is_superuser or getattr(user.role, 'name', '') == 'super_admin'


@login_required
def manage_books(request):
	if not is_admin(request.user):
		from django.http import HttpResponseForbidden
		return HttpResponseForbidden('Only administrators can manage books.')
	books = EBook.objects.select_related('uploaded_by', 'subject', 'grade').order_by('-created_at', '-pk')
	search = request.GET.get('q', '').strip()
	status = request.GET.get('status', '')
	category = request.GET.get('category', '').strip()
	if search:
		books = books.filter(Q(title__icontains=search) | Q(author__icontains=search) | Q(description__icontains=search))
	if status in ('published', 'draft'):
		books = books.filter(is_published=status == 'published')
	if category:
		books = books.filter(category=category)
	return render(request, 'admin/books.html', {
		'page': Paginator(books, 25).get_page(request.GET.get('page')),
		'q': search, 'status': status, 'category': category,
		'categories': EBook.objects.exclude(category='').values_list('category', flat=True).distinct().order_by('category'),
	})


@login_required
def edit_book(request, book_id=None):
	if not is_admin(request.user):
		from django.http import HttpResponseForbidden
		return HttpResponseForbidden('Only administrators can manage books.')
	book = get_object_or_404(EBook, pk=book_id) if book_id is not None else None
	form = EBookForm(request.POST if request.method == 'POST' else None, request.FILES or None, instance=book)
	if request.method == 'POST' and form.is_valid():
		book = form.save(commit=False)
		if not book.pk:
			book.uploaded_by = request.user
		book.save()
		messages.success(request, 'Book saved.' if book.is_published else 'Book saved as draft.')
		return redirect('edit_book', book_id=book.pk)
	return render(request, 'admin/book_form.html', {'form': form, 'book': book})


@login_required
def delete_book(request, book_id):
	if not is_admin(request.user):
		from django.http import HttpResponseForbidden
		return HttpResponseForbidden('Only administrators can manage books.')
	book = get_object_or_404(EBook, pk=book_id)
	if request.method == 'POST' and request.POST.get('confirm') == str(book.pk):
		# Retain uploaded objects: no destructive filesystem cleanup in a request.
		book.delete()
		messages.success(request, 'Book record deleted. Uploaded files retained for controlled cleanup.')
		return redirect('manage_books')
	return render(request, 'admin/book_delete.html', {'book': book})


@login_required
def manage_book_chapters(request, book_id):
	from .book_reader import import_epub, reorder_chapters, extract_pdf_chapter, ReaderError
	from django import forms
	from django.core.exceptions import ValidationError
	from django.db import transaction
	from django.http import HttpResponseForbidden
	if not is_admin(request.user):
		return HttpResponseForbidden('Only administrators can manage chapters.')
	book = get_object_or_404(EBook, pk=book_id)
	form = BookChapterForm(instance=BookChapter(book=book))
	if request.method == 'POST':
		try:
			action = request.POST.get('action', 'add')
			if action == 'import':
				mode = request.POST.get('mode', 'create')
				if mode not in ('create', 'refresh'):
					raise ReaderError('INVALID_MODE', 'Choose create or explicit refresh.')
				result = import_epub(book, mode)
				messages.success(request, f"Import complete: {result['created']} created, {result['updated']} refreshed. Chapter IDs: {result['chapter_ids']}.")
			elif action == 'reorder':
				try:
					ids = [int(value.strip()) for value in request.POST.get('chapter_ids', '').split(',') if value.strip()]
				except ValueError:
					raise ReaderError('INVALID_ORDER', 'Use comma-separated chapter IDs.')
				reorder_chapters(book, ids)
				messages.success(request, 'Chapter order saved; reading state retained.')
			elif action == 'extract-pdf':
				field = forms.IntegerField(min_value=1, max_value=9223372036854775807)
				try:
					chapter_id = field.clean(request.POST.get('chapter_id'))
				except ValidationError:
					raise ReaderError('INVALID_CHAPTER_ID', 'Choose a valid positive chapter ID.')
				chapter = get_object_or_404(book.chapters, pk=chapter_id)
				extract_pdf_chapter(book, chapter)
				messages.success(request, 'PDF range text extracted. Review it before publishing.')
			elif action == 'add':
				with transaction.atomic():
					EBook.objects.select_for_update().get(pk=book.pk)
					form = BookChapterForm(request.POST, instance=BookChapter(book=book))
					if not form.is_valid():
						return render(request, 'admin/book_chapters.html', {'book': book, 'chapters': book.chapters.all(), 'form': form})
					form.save()
				messages.success(request, 'Chapter added.')
			else:
				raise ReaderError('INVALID_ACTION', 'Choose a valid chapter action.')
			return redirect('manage_book_chapters', book_id=book.pk)
		except ReaderError as exc:
			messages.error(request, str(exc.detail['detail']))
	return render(request, 'admin/book_chapters.html', {'book': book, 'chapters': book.chapters.all(), 'form': form})


@login_required
def edit_book_chapter(request, book_id, chapter_id):
	from django.http import HttpResponseForbidden
	from django.db import transaction
	if not is_admin(request.user):
		return HttpResponseForbidden('Only administrators can manage chapters.')
	book = get_object_or_404(EBook, pk=book_id)
	chapter = get_object_or_404(book.chapters, pk=chapter_id)
	with transaction.atomic():
		if request.method == 'POST':
			EBook.objects.select_for_update().get(pk=book.pk)
			chapter = get_object_or_404(book.chapters.select_for_update(), pk=chapter_id)
		form = BookChapterForm(request.POST if request.method == 'POST' else None, instance=chapter)
		if request.method == 'POST' and form.is_valid():
			form.save()
			messages.success(request, 'Chapter saved; progress and bookmarks retained.')
			return redirect('edit_book_chapter', book_id=book.pk, chapter_id=chapter.pk)
	return render(request, 'admin/book_chapter_form.html', {'book': book, 'chapter': chapter, 'form': form})


@login_required
def delete_book_chapter(request, book_id, chapter_id):
	from django.http import HttpResponseForbidden
	from django.db import transaction
	if not is_admin(request.user):
		return HttpResponseForbidden('Only administrators can manage chapters.')
	book = get_object_or_404(EBook, pk=book_id)
	chapter = get_object_or_404(book.chapters, pk=chapter_id)
	if request.method == 'POST' and request.POST.get('confirm') == str(chapter.pk):
		with transaction.atomic():
			EBook.objects.select_for_update().get(pk=book.pk)
			chapter.delete()
		messages.success(request, 'Chapter deleted. Book files retained; dependent chapter bookmarks/completions removed.')
		return redirect('manage_book_chapters', book_id=book.pk)
	return render(request, 'admin/book_chapter_delete.html', {'book': book, 'chapter': chapter})


def _log_admin_action(admin, action, target_user, details=''):
	AdminAuditLog.objects.create(
		admin=admin,
		action=action,
		target_user=target_user,
		details=details,
	)


def _other_active_admin_exists(target):
	return User.objects.filter(
		is_active=True,
	).filter(
		Q(is_superuser=True) | Q(role__name='super_admin')
	).exclude(
		pk=target.pk
	).exists()


@login_required
def verification_queue(request):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to review verifications.')
		return redirect('dashboard')

	pending_users = User.objects.filter(
		verification_status='pending',
	).select_related('role').prefetch_related(
		'verification_documents', 'student_profile', 'instructor_profile',
	).order_by('created_at')

	return render(request, 'admin/verifications.html', {'pending_users': pending_users})


@login_required
def review_verification(request, user_id):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to review verifications.')
		return redirect('dashboard')

	user = User.objects.filter(pk=user_id).first()
	if user is None:
		messages.error(request, 'User not found.')
		return redirect('verification_queue')

	if request.method == 'POST':
		action = request.POST.get('action')
		if action == 'approve':
			user.verification_status = 'verified'
			user.verified_by = request.user
			user.verified_at = timezone.now()
			user.save(update_fields=['verification_status', 'verified_by', 'verified_at'])
			_log_admin_action(request.user, 'verification_approved', user)
			messages.success(request, f'{user.name} has been verified.')
		elif action == 'reject':
			user.verification_status = 'rejected'
			user.verified_by = request.user
			user.verified_at = timezone.now()
			user.save(update_fields=['verification_status', 'verified_by', 'verified_at'])
			_log_admin_action(request.user, 'verification_rejected', user)
			messages.warning(request, f'{user.name} has been rejected.')
		else:
			messages.error(request, 'Invalid action.')

	return redirect('verification_queue')


@login_required
def view_document(request, document_id):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to view documents.')
		return redirect('dashboard')

	document = VerificationDocument.objects.filter(pk=document_id).first()
	if document is None:
		raise Http404('Document not found.')

	return document_file_response(document)


@login_required
def manage_users(request):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage users.')
		return redirect('dashboard')

	query = request.GET.get('q', '').strip()
	role_filter = request.GET.get('role', '').strip()
	status_filter = request.GET.get('status', '').strip()
	verification_filter = request.GET.get('verification', '').strip()

	users = User.objects.select_related('role').order_by('-created_at')

	if query:
		users = users.filter(Q(name__icontains=query) | Q(email__icontains=query))

	if role_filter:
		users = users.filter(role__name=role_filter)

	if status_filter == 'active':
		users = users.filter(is_active=True)
	elif status_filter == 'inactive':
		users = users.filter(is_active=False)

	if verification_filter in dict(User.VERIFICATION_CHOICES):
		users = users.filter(verification_status=verification_filter)

	page = Paginator(users, 20).get_page(request.GET.get('page'))

	params = request.GET.copy()
	params.pop('page', None)

	return render(request, 'admin/users.html', {
		'page': page,
		'roles': Role.objects.order_by('name'),
		'verification_choices': User.VERIFICATION_CHOICES,
		'filters': {
			'q': query,
			'role': role_filter,
			'status': status_filter,
			'verification': verification_filter,
		},
		'query_string': params.urlencode(),
	})


@login_required
def edit_user(request, user_id):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage users.')
		return redirect('dashboard')

	target = User.objects.select_related('role').filter(pk=user_id).first()
	if target is None:
		messages.error(request, 'User not found.')
		return redirect('manage_users')

	target_name = target.name

	if request.method == 'POST':
		form = UserAdminForm(request.POST, instance=target)
		if form.is_valid():
			if form.has_changed():
				form.save()
				_log_admin_action(
					request.user,
					'user_updated',
					target,
					'Updated fields: ' + ', '.join(form.changed_data),
				)
				messages.success(request, f'{target.name} has been updated.')
			else:
				messages.info(request, 'No changes to save.')
			return redirect('edit_user', user_id=target.pk)
	else:
		form = UserAdminForm(instance=target)

	return render(request, 'admin/user_edit.html', {
		'form': form,
		'target': target,
		'target_name': target_name,
		'documents': target.verification_documents.order_by('-uploaded_at', '-pk'),
		'audit_entries': target.audit_entries.select_related('admin')[:10],
	})


@login_required
@require_POST
def toggle_user_active(request, user_id):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage users.')
		return redirect('dashboard')

	target = User.objects.select_related('role').filter(pk=user_id).first()
	if target is None:
		messages.error(request, 'User not found.')
		return redirect('manage_users')

	action = request.POST.get('action')

	if action == 'deactivate':
		if target.pk == request.user.pk:
			messages.error(request, 'You cannot deactivate your own account.')
		elif is_admin(target) and not _other_active_admin_exists(target):
			messages.error(request, 'You cannot deactivate the last active administrator.')
		elif not target.is_active:
			messages.info(request, f'{target.name} is already inactive.')
		else:
			target.is_active = False
			target.save(update_fields=['is_active', 'updated_at'])
			_log_admin_action(request.user, 'user_deactivated', target)
			messages.warning(request, f'{target.name} has been deactivated.')

	elif action == 'reactivate':
		if target.is_active:
			messages.info(request, f'{target.name} is already active.')
		else:
			target.is_active = True
			target.save(update_fields=['is_active', 'updated_at'])
			_log_admin_action(request.user, 'user_reactivated', target)
			messages.success(request, f'{target.name} has been reactivated.')

	else:
		messages.error(request, 'Invalid action.')

	next_url = request.POST.get('next', '')
	if next_url and url_has_allowed_host_and_scheme(
		next_url,
		allowed_hosts={request.get_host()},
		require_https=request.is_secure(),
	):
		return redirect(next_url)

	return redirect('manage_users')


@login_required
def manage_courses(request):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage courses.')
		return redirect('dashboard')

	form = CourseForm()
	if request.method == 'POST':
		form = CourseForm(request.POST)
		if form.is_valid():
			course = form.save()
			messages.success(request, f'Course "{course.title}" added successfully.')
			return redirect('manage_courses')

	return render(request, 'admin/courses.html', {
		'form': form,
		'courses': Course.objects.filter(course_type__in=['academic', 'skill', 'premium']).select_related('instructor', 'subject', 'grade').order_by('-created_at', '-pk'),
	})


@login_required
def manage_bootcamps(request):
	if not is_admin(request.user):
		return redirect('dashboard')
	bootcamps = Course.objects.filter(course_type='bootcamp').select_related('bootcamp_profile', 'instructor').annotate(
		instructors_count=Count('instructors', distinct=True),
		lessons_count=Count('lessons', distinct=True),
		enrolled_count=Count('enrollments', filter=Q(enrollments__status__in=['active', 'completed']), distinct=True),
	).order_by('-created_at', '-pk')
	return render(request, 'admin/bootcamps.html', {'bootcamps': bootcamps})


@login_required
def add_bootcamp(request):
	if not is_admin(request.user):
		return redirect('dashboard')
	form = BootcampForm(request.POST if request.method == 'POST' else None)
	if request.method == 'POST' and form.is_valid():
		course = form.save()
		messages.success(request, f'Bootcamp "{course.title}" added.')
		return redirect('manage_bootcamp_content', course_id=course.pk)
	return render(request, 'admin/bootcamp_form.html', {'form': form, 'heading': 'Add Bootcamp'})


@login_required
def manage_bootcamp_instructors(request, course_id):
	if not is_admin(request.user):
		return redirect('dashboard')
	course = get_object_or_404(Course, pk=course_id, course_type='bootcamp')
	form = BootcampInstructorForm(request.POST if request.method == 'POST' else None, instance=course)
	if request.method == 'POST' and form.is_valid():
		form.save()
		messages.success(request, 'Instructor roster updated.')
		return redirect('manage_bootcamp_instructors', course_id=course.pk)
	return render(request, 'admin/bootcamp_form.html', {'form': form, 'course': course, 'heading': 'Manage Instructors'})


@login_required
def manage_bootcamp_content(request, course_id):
	"""A bootcamp's lessons and files, from the dashboard.

	Dashboard authoring is admin-only, including for roster instructors.
	"""
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage bootcamps.')
		return redirect('dashboard')

	course = get_object_or_404(
		Course.objects.select_related('bootcamp_profile', 'instructor'),
		pk=course_id,
	)
	if course.course_type != 'bootcamp':
		messages.error(request, 'That course is not a bootcamp.')
		return redirect('manage_courses')

	lesson_id = request.POST.get('lesson_id') if request.method == 'POST' else request.GET.get('lesson_id')
	resource_id = request.POST.get('resource_id') if request.method == 'POST' else request.GET.get('resource_id')
	# Resolve all edits/deletes within this bootcamp, including forged IDs.
	if any(value and (not value.isascii() or not value.isdecimal() or len(value) > 18) for value in [lesson_id, resource_id]):
		raise Http404
	editing_lesson = get_object_or_404(Lesson, pk=lesson_id, course=course) if lesson_id else None
	editing_resource = get_object_or_404(CourseResource, pk=resource_id, course=course) if resource_id else None
	lesson_form = BootcampLessonForm(bootcamp=course, instance=editing_lesson)
	resource_form = BootcampResourceForm(bootcamp=course, instance=editing_resource)
	details_form = BootcampForm(instance=course)

	if request.method == 'POST':
		action = request.POST.get('form')
		if action == 'details':
			details_form = BootcampForm(request.POST, instance=course)
			if details_form.is_valid():
				details_form.save()
				messages.success(request, 'Bootcamp details updated.')
				return redirect('manage_bootcamp_content', course_id=course.pk)
		elif action == 'lesson':
			lesson_form = BootcampLessonForm(request.POST, request.FILES, bootcamp=course, instance=editing_lesson)
			if lesson_form.is_valid():
				lesson = lesson_form.save(course, request=request)
				messages.success(request, f'Lesson "{lesson.title}" saved to Day {lesson.day_number}.')
				return redirect('manage_bootcamp_content', course_id=course.pk)
		elif action == 'resource':
			resource_form = BootcampResourceForm(request.POST, request.FILES, bootcamp=course, instance=editing_resource)
			if resource_form.is_valid():
				resource = resource_form.save(course, request=request)
				messages.success(request, f'File "{resource.title}" saved.')
				return redirect('manage_bootcamp_content', course_id=course.pk)
		elif action == 'delete_lesson':
			Lesson.objects.filter(pk=request.POST.get('lesson_id'), course=course).delete()
			messages.success(request, 'Lesson removed.')
			return redirect('manage_bootcamp_content', course_id=course.pk)
		elif action == 'delete_resource':
			CourseResource.objects.filter(pk=request.POST.get('resource_id'), course=course).delete()
			messages.success(request, 'File removed.')
			return redirect('manage_bootcamp_content', course_id=course.pk)

	lessons = Lesson.objects.filter(course=course).order_by('day_number', 'order', 'pk')
	resources = CourseResource.objects.filter(course=course).select_related('lesson').order_by('order', 'pk')

	# Grouped here rather than in the template: the page mirrors the app's Day
	# tabs, and `regroup` on a nullable `day_number` would print an empty tab.
	profile = getattr(course, 'bootcamp_profile', None)
	days = {day: [] for day in range(1, profile.days + 1)} if profile else {}
	for lesson in lessons:
		days.setdefault(lesson.day_number or 1, []).append(lesson)

	return render(request, 'admin/bootcamp_content.html', {
		'course': course,
		'profile': getattr(course, 'bootcamp_profile', None),
		'details_form': details_form,
		'lesson_form': lesson_form,
		'resource_form': resource_form,
		'days': sorted(days.items()),
		'resources': resources,
		'lessons_count': lessons.count(),
		'editing_lesson': editing_lesson,
		'editing_resource': editing_resource,
	})


@login_required
def manage_streak_settings(request):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage streak settings.')
		return redirect('dashboard')

	settings_row = StreakSettings.get_solo()

	if request.method == 'POST':
		form = StreakSettingsForm(request.POST, instance=settings_row)
		if form.is_valid():
			form.save()
			messages.success(request, 'Streak settings updated successfully.')
			return redirect('manage_streak_settings')
	else:
		form = StreakSettingsForm(instance=settings_row)

	return render(request, 'admin/streak_settings.html', {'form': form, 'settings': settings_row})


@login_required
def manage_certificate_criteria(request):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage certificate criteria.')
		return redirect('dashboard')

	criteria = CertificateCriteria.get_solo()

	if request.method == 'POST':
		form = CertificateCriteriaForm(request.POST, instance=criteria)
		if form.is_valid():
			form.save()
			messages.success(request, 'Certificate criteria updated successfully.')
			return redirect('manage_certificate_criteria')
	else:
		form = CertificateCriteriaForm(instance=criteria)

	return render(request, 'admin/certificate_criteria.html', {'form': form})


@require_POST
def logout_view(request):
	logout(request)
	return redirect('login')


# =========================================================
# Events
# =========================================================

EVENT_TIMEZONE = 'Asia/Kathmandu'


@login_required
def manage_events(request):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage events.')
		return redirect('dashboard')

	with timezone.override(EVENT_TIMEZONE):
		form = EventForm()
		if request.method == 'POST':
			form = EventForm(request.POST, request.FILES)
			if form.is_valid():
				event = form.save(commit=False)
				event.created_by = request.user
				event.save()
				messages.success(request, f'Event "{event.title}" created.')
				return redirect('manage_events')

		events = Event.objects.select_related('host', 'district').annotate(
			registered_count=Count('registrations', filter=Q(registrations__status='registered')),
			waitlist_count=Count('registrations', filter=Q(registrations__status='waitlisted')),
		).order_by('-start_at')

		return render(request, 'admin/events.html', {
			'form': form,
			'events': events,
			'now': timezone.now(),
		})


@login_required
def edit_event(request, event_id):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage events.')
		return redirect('dashboard')

	event = get_object_or_404(Event, pk=event_id)
	old_cover = event.cover_image.name

	with timezone.override(EVENT_TIMEZONE):
		if request.method == 'POST':
			form = EventForm(request.POST, request.FILES, instance=event)
			if form.is_valid():
				event = form.save()
				if old_cover and old_cover != event.cover_image.name:
					event.cover_image.storage.delete(old_cover)
				messages.success(request, f'Event "{event.title}" updated.')
				return redirect('edit_event', event_id=event.pk)
		else:
			form = EventForm(instance=event)

		return render(request, 'admin/event_edit.html', {
			'form': form,
			'event': event,
			'registrations': event.registrations.select_related('user'),
		})


@login_required
@require_POST
def delete_event(request, event_id):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage events.')
		return redirect('dashboard')

	event = get_object_or_404(Event, pk=event_id)
	title, cover = event.title, event.cover_image.name
	storage = event.cover_image.storage
	event.delete()
	if cover:
		storage.delete(cover)
	messages.success(request, f'Event "{title}" deleted.')
	return redirect('manage_events')


# =========================================================
# Banners (the Home carousel; stored as Advertisement)
# =========================================================

def _banner_status(banner, now):
	if banner.archived_at is not None:
		return 'archived'
	if not banner.is_active:
		return 'off'
	if banner.ends_at is not None and banner.ends_at < now:
		return 'expired'
	if banner.starts_at is not None and banner.starts_at > now:
		return 'scheduled'
	return 'live'


def _ordered_banners():
	return list(Advertisement.objects.filter(archived_at__isnull=True).order_by('display_order', 'id'))


def _renumber_banners(banners):
	"""Store positions 1..n so ties from older rows never block a move."""
	for position, banner in enumerate(banners, start=1):
		if banner.display_order != position:
			banner.display_order = position
			banner.save(update_fields=['display_order', 'updated_at'])


def _audit_banner(request, action, banner, before):
	from .advertisement_views import advertisement_snapshot
	from .api_views import _create_audit_log
	_create_audit_log(request, action, 'advertisement', banner.pk, banner.title,
		metadata={'before': before, 'after': advertisement_snapshot(banner), 'source': 'admin_dashboard'})


def _delete_replaced_banner_image(storage, old_name, new_name):
	if old_name and old_name != new_name and not Advertisement.objects.filter(banner_image=old_name).exists():
		storage.delete(old_name)


@login_required
def manage_banners(request):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage banners.')
		return redirect('dashboard')

	with timezone.override(EVENT_TIMEZONE):
		form = BannerForm(initial={'is_active': True})
		if request.method == 'POST':
			form = BannerForm(request.POST, request.FILES)
			if form.is_valid():
				banner = form.save(commit=False)
				banner.created_by = request.user
				banner.display_order = len(_ordered_banners()) + 1
				banner.save()
				_audit_banner(request, 'create', banner, None)
				messages.success(request, f'Banner "{banner.title}" added.')
				return redirect('manage_banners')

		now = timezone.now()
		banners = _ordered_banners()
		archived = list(Advertisement.objects.filter(archived_at__isnull=False).order_by('-archived_at'))
		for banner in banners + archived:
			banner.status = _banner_status(banner, now)
		return render(request, 'admin/banners.html', {
			'form': form,
			'banners': banners,
			'archived': archived,
			'live_count': sum(1 for banner in banners if banner.status == 'live'),
		})


@login_required
def edit_banner(request, banner_id):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage banners.')
		return redirect('dashboard')

	from .advertisement_views import advertisement_snapshot
	banner = get_object_or_404(Advertisement, pk=banner_id)
	if banner.archived_at is not None:
		messages.error(request, 'Restore this banner before editing it.')
		return redirect('manage_banners')
	old_image = banner.banner_image.name

	with timezone.override(EVENT_TIMEZONE):
		if request.method == 'POST':
			before = advertisement_snapshot(banner)
			form = BannerForm(request.POST, request.FILES, instance=banner)
			if form.is_valid():
				banner = form.save()
				_audit_banner(request, 'update', banner, before)
				_delete_replaced_banner_image(banner.banner_image.storage, old_image, banner.banner_image.name)
				messages.success(request, f'Banner "{banner.title}" saved.')
				return redirect('manage_banners')
		else:
			form = BannerForm(instance=banner)
		return render(request, 'admin/banner_edit.html', {
			'form': form,
			'banner': banner,
			'status': _banner_status(banner, timezone.now()),
		})


@login_required
@require_POST
def banner_action(request, banner_id):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage banners.')
		return redirect('dashboard')

	from .advertisement_views import advertisement_snapshot
	action = request.POST.get('action')
	banner = get_object_or_404(Advertisement, pk=banner_id)
	before = advertisement_snapshot(banner)

	if action == 'restore':
		if banner.archived_at is not None:
			banner.archived_at = None
			banner.display_order = len(_ordered_banners()) + 1
			banner.save(update_fields=['archived_at', 'display_order', 'updated_at'])
			_audit_banner(request, 'update', banner, before)
			messages.success(request, f'Banner "{banner.title}" restored. It is off until you turn it on.')
		return redirect('manage_banners')

	if banner.archived_at is not None:
		messages.error(request, 'Restore this banner first.')
		return redirect('manage_banners')

	if action == 'toggle':
		banner.is_active = not banner.is_active
		banner.save(update_fields=['is_active', 'updated_at'])
		_audit_banner(request, 'activate' if banner.is_active else 'deactivate', banner, before)
		messages.success(request, f'Banner "{banner.title}" turned {"on" if banner.is_active else "off"}.')
	elif action in ('up', 'down'):
		banners = _ordered_banners()
		index = next(i for i, row in enumerate(banners) if row.pk == banner.pk)
		target = index - 1 if action == 'up' else index + 1
		if 0 <= target < len(banners):
			banners[index], banners[target] = banners[target], banners[index]
			_renumber_banners(banners)
	elif action == 'archive':
		banner.archived_at = timezone.now()
		banner.is_active = False
		banner.save(update_fields=['archived_at', 'is_active', 'updated_at'])
		_renumber_banners(_ordered_banners())
		_audit_banner(request, 'delete', banner, before)
		messages.success(request, f'Banner "{banner.title}" archived. Restore it any time from the archive.')
	else:
		messages.error(request, 'Unknown action.')
	return redirect('manage_banners')


# =========================================================
# Payments
# =========================================================

@login_required
def manage_payments(request):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to view payments.')
		return redirect('dashboard')

	status_filter = request.GET.get('status', '').strip()
	provider_filter = request.GET.get('provider', '').strip()
	query = request.GET.get('q', '').strip()

	payments = Payment.objects.select_related('student', 'course').order_by('-created_at')
	if status_filter in dict(Payment.STATUS_CHOICES):
		payments = payments.filter(status=status_filter)
	if provider_filter in dict(Payment.PROVIDER_CHOICES):
		payments = payments.filter(provider=provider_filter)
	if query:
		payments = payments.filter(
			Q(student__name__icontains=query) | Q(student__email__icontains=query)
			| Q(course__title__icontains=query) | Q(transaction_reference__icontains=query)
			| Q(gateway_transaction_id__icontains=query)
		)

	successful = Payment.objects.filter(status='successful')
	params = request.GET.copy()
	params.pop('page', None)

	with timezone.override(EVENT_TIMEZONE):
		return render(request, 'admin/payments.html', {
			'page': Paginator(payments, 25).get_page(request.GET.get('page')),
			'status_choices': Payment.STATUS_CHOICES,
			'provider_choices': Payment.PROVIDER_CHOICES,
			'filters': {'status': status_filter, 'provider': provider_filter, 'q': query},
			'query_string': params.urlencode(),
			'revenue': successful.aggregate(total=Sum('amount'))['total'] or 0,
			'successful_count': successful.count(),
			'pending_count': Payment.objects.filter(status='initiated').count(),
		})


@login_required
@require_POST
def recheck_payment(request, payment_id):
	if not is_admin(request.user):
		messages.error(request, 'You do not have permission to manage payments.')
		return redirect('dashboard')

	payment = get_object_or_404(Payment, pk=payment_id)
	try:
		payment = refresh_payment(payment.pk, settle_missing=True)
		messages.success(request, f'Payment #{payment.pk} is now: {payment.get_status_display()}.')
	except GatewayError as exc:
		messages.error(request, f'Could not reach the gateway for payment #{payment.pk}: {exc}')

	next_url = request.POST.get('next', '')
	if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
		return redirect(next_url)
	return redirect('manage_payments')
