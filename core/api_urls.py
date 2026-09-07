from django.urls import path

from .api_views import (
	DistrictListAPIView,
	GradeListAPIView,
	InstructorRegistrationAPIView,
	MunicipalityListAPIView,
	ProvinceListAPIView,
	RoleListAPIView,
	SchoolListAPIView,
	StudentRegistrationAPIView,
)


urlpatterns = [
	path('roles/', RoleListAPIView.as_view(), name='api-roles'),
	path('register/student/', StudentRegistrationAPIView.as_view(), name='api-register-student'),
	path('register/instructor/', InstructorRegistrationAPIView.as_view(), name='api-register-instructor'),
	path('locations/provinces/', ProvinceListAPIView.as_view(), name='api-provinces'),
	path('locations/districts/', DistrictListAPIView.as_view(), name='api-districts'),
	path('locations/municipalities/', MunicipalityListAPIView.as_view(), name='api-municipalities'),
	path('locations/schools/', SchoolListAPIView.as_view(), name='api-schools'),
	path('grades/', GradeListAPIView.as_view(), name='api-grades'),
]
