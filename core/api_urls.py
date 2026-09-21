from django.urls import path

from rest_framework_simplejwt.views import TokenRefreshView

from .api_views import (
	ChapterDetailAPIView,
	ChapterListCreateAPIView,
	CheckCourseCertificateAPIView,
	CheckGradeCertificateAPIView,
	CompleteLessonAPIView,
	CourseDetailAPIView,
	CourseListCreateAPIView,
	CourseProgressAPIView,
	CurrentUserAPIView,
	DistrictListAPIView,
	EnrollCourseAPIView,
	ForgotPasswordAPIView,
	GradeListAPIView,
	InitiatePaymentAPIView,
	InstructorQuizResultsAPIView,
	InstructorRegistrationAPIView,
	LessonDetailAPIView,
	LessonListCreateAPIView,
	LoginAPIView,
	LogoutAPIView,
	MunicipalityListAPIView,
	MyCertificatesAPIView,
	MyEnrollmentsAPIView,
	MyPaymentsAPIView,
	MyStreakAPIView,
	PaymentStatusAPIView,
	ProvinceListAPIView,
	QuestionDetailAPIView,
	QuestionListCreateAPIView,
	QuestionOptionDetailAPIView,
	QuestionOptionListCreateAPIView,
	QuizDetailAPIView,
	QuizListCreateAPIView,
	ResetPasswordAPIView,
	RoleListAPIView,
	SchoolListAPIView,
	StartQuizAttemptAPIView,
	StreakLeaderboardAPIView,
	StudentPointsAPIView,
	StudentQuizAttemptHistoryAPIView,
	StudentQuizDetailAPIView,
	StudentRegistrationAPIView,
	SubjectDetailAPIView,
	SubjectListCreateAPIView,
	SubmitQuizAttemptAPIView,
	TopicDetailAPIView,
	TopicListCreateAPIView,
	VerifyPasswordResetOTPAPIView,
	VerifyPaymentAPIView,
	PointsLeaderboardAPIView,
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

	# =========================
	# Enrollment & Progress
	# =========================

	path(
		'courses/<int:course_id>/enroll/',
		EnrollCourseAPIView.as_view(),
		name='api-enroll-course'
	),

	path(
		'my-enrollments/',
		MyEnrollmentsAPIView.as_view(),
		name='api-my-enrollments'
	),

	path(
		'lessons/<int:lesson_id>/complete/',
		CompleteLessonAPIView.as_view(),
		name='api-complete-lesson'
	),

	path(
		'courses/<int:course_id>/progress/',
		CourseProgressAPIView.as_view(),
		name='api-course-progress'
	),

	# =========================
	# Payment
	# =========================

	path(
		'courses/<int:course_id>/initiate-payment/',
		InitiatePaymentAPIView.as_view(),
		name='api-initiate-payment'
	),

	path(
		'payments/verify/',
		VerifyPaymentAPIView.as_view(),
		name='api-verify-payment'
	),

	path(
		'payments/<int:payment_id>/',
		PaymentStatusAPIView.as_view(),
		name='api-payment-status'
	),

	path(
		'my-payments/',
		MyPaymentsAPIView.as_view(),
		name='api-my-payments'
	),

	# =========================
	# Streak
	# =========================

	path(
		'my-streak/',
		MyStreakAPIView.as_view(),
		name='api-my-streak'
	),

	path(
		'streak-leaderboard/',
		StreakLeaderboardAPIView.as_view(),
		name='api-streak-leaderboard'
	),

	# =========================
	# Certificate
	# =========================

	path(
		'courses/<int:course_id>/certificate/',
		CheckCourseCertificateAPIView.as_view(),
		name='api-check-course-certificate'
	),

	path(
		'grade-certificate/',
		CheckGradeCertificateAPIView.as_view(),
		name='api-check-grade-certificate'
	),

	path(
		'my-certificates/',
		MyCertificatesAPIView.as_view(),
		name='api-my-certificates'
	),

	# =========================
	# Quiz Management
	# =========================

	path(
		'quizzes/',
		QuizListCreateAPIView.as_view(),
		name='api-quiz-list-create'
	),

	path(
		'quizzes/<int:pk>/',
		QuizDetailAPIView.as_view(),
		name='api-quiz-detail'
	),

	# =========================
	# Question Management
	# =========================

	path(
		'questions/',
		QuestionListCreateAPIView.as_view(),
		name='api-question-list-create'
	),

	path(
		'questions/<int:pk>/',
		QuestionDetailAPIView.as_view(),
		name='api-question-detail'
	),

	# =========================
	# Question Option Management
	# =========================

	path(
		'question-options/',
		QuestionOptionListCreateAPIView.as_view(),
		name='api-question-option-list-create'
	),

	path(
		'question-options/<int:pk>/',
		QuestionOptionDetailAPIView.as_view(),
		name='api-question-option-detail'
	),

	# =========================
	# Student Quiz Access
	# =========================

	path(
		'student/quizzes/<int:pk>/',
		StudentQuizDetailAPIView.as_view(),
		name='student-quiz-detail',
	),

	path(
		'student/quizzes/<int:quiz_id>/start/',
		StartQuizAttemptAPIView.as_view(),
		name='start-quiz-attempt',
	),

	path(
		'student/quiz-attempts/<int:attempt_id>/submit/',
		SubmitQuizAttemptAPIView.as_view(),
		name='submit-quiz-attempt',
	),

	path(
		'student/quiz-attempts/history/',
		StudentQuizAttemptHistoryAPIView.as_view(),
		name='student-quiz-attempt-history',
	),

	path(
		'instructor/quizzes/<int:quiz_id>/results/',
		InstructorQuizResultsAPIView.as_view(),
		name='instructor-quiz-results',
	),

	# =========================
	# Student Points
	# =========================

	path(
		'student/points/',
		StudentPointsAPIView.as_view(),
		name='student-points',
	),
		# =========================
	# Points Leaderboard
	# =========================

	path(
		'points-leaderboard/',
		PointsLeaderboardAPIView.as_view(),
		name='api-points-leaderboard',
	),

	# =========================
	# Student Points
	# =========================

	path(
		'student/points/',
		StudentPointsAPIView.as_view(),
		name='student-points',
	),
]