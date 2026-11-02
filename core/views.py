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
	BootcampForm,
	BootcampInstructorForm,
	BootcampLessonForm,
	BootcampResourceForm,
	CertificateCriteriaForm,
	CourseForm,
	DistrictForm,
	EventForm,
	GradeForm,
	MunicipalityForm,
	ProvinceForm,
	SchoolForm,
	StreakSettingsForm,
	UserAdminForm,
)
from .models import (
	Event,
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
		'courses': Course.objects.filter(course_type__in=['academic', 'skill', 'premium']).select_related('instructor', 'subject', 'grade').order_by('-created_at'),
	})


@login_required
def manage_bootcamps(request):
	if not is_admin(request.user):
		return redirect('dashboard')
	bootcamps = Course.objects.filter(course_type='bootcamp').select_related('bootcamp_profile', 'instructor').annotate(
		instructors_count=Count('instructors', distinct=True),
		lessons_count=Count('lessons', distinct=True),
		enrolled_count=Count('enrollments', filter=Q(enrollments__status__in=['active', 'completed']), distinct=True),
	).order_by('-created_at')
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
