from django.urls import path

from rest_framework_simplejwt.views import TokenRefreshView

from .api_views import (
    ChapterDetailAPIView,
    ChapterListCreateAPIView,
    CourseDetailAPIView,
    CourseListCreateAPIView,
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
    SubjectDetailAPIView,
    SubjectListCreateAPIView,
    TopicDetailAPIView,
    TopicListCreateAPIView,
    VerifyPasswordResetOTPAPIView,
	LessonDetailAPIView,
    LessonListCreateAPIView, 
)


urlpatterns = [
    # =========================
    # Roles
    # =========================

    path(
        'roles/',
        RoleListAPIView.as_view(),
        name='api-roles'
    ),

    # =========================
    # Registration
    # =========================

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

    # =========================
    # Authentication
    # =========================

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

    # =========================
    # Password Reset
    # =========================

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

    # =========================
    # Location Lookups
    # =========================

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

    # =========================
    # Subject Management
    # =========================

    path(
        'subjects/',
        SubjectListCreateAPIView.as_view(),
        name='api-subject-list-create'
    ),

    path(
        'subjects/<int:pk>/',
        SubjectDetailAPIView.as_view(),
        name='api-subject-detail'
    ),

    # =========================
    # Chapter Management
    # =========================

    path(
        'chapters/',
        ChapterListCreateAPIView.as_view(),
        name='api-chapter-list-create'
    ),

    path(
        'chapters/<int:pk>/',
        ChapterDetailAPIView.as_view(),
        name='api-chapter-detail'
    ),

    # =========================
    # Topic Management
    # =========================

    path(
        'topics/',
        TopicListCreateAPIView.as_view(),
        name='api-topic-list-create'
    ),

    path(
        'topics/<int:pk>/',
        TopicDetailAPIView.as_view(),
        name='api-topic-detail'
    ),

    # =========================
    # Course Management
    # =========================

    path(
        'courses/',
        CourseListCreateAPIView.as_view(),
        name='api-course-list-create'
    ),

    path(
        'courses/<int:pk>/',
        CourseDetailAPIView.as_view(),
        name='api-course-detail'
    ),

	    path(
        'lessons/',
        LessonListCreateAPIView.as_view(),
        name='api-lesson-list-create'
    ),

    path(
        'lessons/<int:pk>/',
        LessonDetailAPIView.as_view(),
        name='api-lesson-detail'
    ),
]