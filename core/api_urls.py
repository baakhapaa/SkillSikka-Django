from django.urls import path

from rest_framework_simplejwt.views import TokenRefreshView

from .api_views import (
	CurrentUserAPIView,
	DistrictListAPIView,
	ForgotPasswordAPIView,
	GradeListAPIView,
	InstructorRegistrationAPIView,
	LoginAPIView,
	LogoutAPIView,
	MunicipalityListAPIView,
	ProvinceListAPIView,
	ResetPasswordAPIView,
	RoleListAPIView,
	SchoolListAPIView,
	StudentRegistrationAPIView,
	VerifyPasswordResetOTPAPIView,
)


urlpatterns = [
	path(
		'roles/',
		RoleListAPIView.as_view(),
		name='api-roles'
	),

	path(
		'register/student/',
		StudentRegistrationAPIView.as_view(),
		name='api-register-student'
	),

	path(
		'register/instructor/',
		InstructorRegistrationAPIView.as_view(),
		name='api-register-instructor'
	),

	path(
		'login/',
		LoginAPIView.as_view(),
		name='api-login'
	),

	path(
		'me/',
		CurrentUserAPIView.as_view(),
		name='api-current-user'
	),

	path(
		'token/refresh/',
		TokenRefreshView.as_view(),
		name='api-token-refresh'
	),

	path(
		'logout/',
		LogoutAPIView.as_view(),
		name='api-logout'
	),

	path(
		'forgot-password/',
		ForgotPasswordAPIView.as_view(),
		name='api-forgot-password'
	),

	path(
		'forgot-password/verify-otp/',
		VerifyPasswordResetOTPAPIView.as_view(),
		name='api-forgot-password-verify'
	),

	path(
		'forgot-password/reset/',
		ResetPasswordAPIView.as_view(),
		name='api-password-reset'
	),

	path(
		'locations/provinces/',
		ProvinceListAPIView.as_view(),
		name='api-provinces'
	),

	path(
		'locations/districts/',
		DistrictListAPIView.as_view(),
		name='api-districts'
	),

	path(
		'locations/municipalities/',
		MunicipalityListAPIView.as_view(),
		name='api-municipalities'
	),

	path(
		'locations/schools/',
		SchoolListAPIView.as_view(),
		name='api-schools'
	),

	path(
		'grades/',
		GradeListAPIView.as_view(),
		name='api-grades'
	),
]