from django.urls import path

from .views import (
	dashboard,
	login_view,
	logout_view,
	manage_geography,
	review_verification,
	verification_queue,
)


urlpatterns = [
	path('', dashboard, name='dashboard'),
	path('login', login_view, name='login'),
	path('logout', logout_view, name='logout'),
	path('admin/geography', manage_geography, name='manage_geography'),
	path('admin/verifications', verification_queue, name='verification_queue'),
	path('admin/verifications/<int:user_id>/review', review_verification, name='review_verification'),
]