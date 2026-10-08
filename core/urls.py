from django.urls import path

from .views import (
	dashboard,
	delete_event,
	edit_event,
	edit_user,
	login_view,
	logout_view,
	manage_events,
	manage_payments,
	manage_certificate_criteria,
	manage_courses,
	manage_geography,
	manage_streak_settings,
	manage_users,
	recheck_payment,
	review_verification,
	toggle_user_active,
	verification_queue,
	view_document,
)


urlpatterns = [
	path('', dashboard, name='dashboard'),
	path('login', login_view, name='login'),
	path('logout', logout_view, name='logout'),
	path('admin/geography', manage_geography, name='manage_geography'),
	path('admin/verifications', verification_queue, name='verification_queue'),
	path('admin/verifications/<int:user_id>/review', review_verification, name='review_verification'),
	path('admin/documents/<int:document_id>', view_document, name='view_document'),
	path('admin/users', manage_users, name='manage_users'),
	path('admin/users/<int:user_id>/edit', edit_user, name='edit_user'),
	path('admin/users/<int:user_id>/status', toggle_user_active, name='toggle_user_active'),
	path('admin/courses', manage_courses, name='manage_courses'),
	path('admin/events', manage_events, name='manage_events'),
	path('admin/events/<int:event_id>/edit', edit_event, name='edit_event'),
	path('admin/events/<int:event_id>/delete', delete_event, name='delete_event'),
	path('admin/payments', manage_payments, name='manage_payments'),
	path('admin/payments/<int:payment_id>/recheck', recheck_payment, name='recheck_payment'),
	path('admin/streak-settings', manage_streak_settings, name='manage_streak_settings'),
	path('admin/certificate-criteria', manage_certificate_criteria, name='manage_certificate_criteria'),
]