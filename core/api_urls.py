from django.urls import path

from rest_framework_simplejwt.views import TokenRefreshView

from .analytics_views import (
	TeacherChallengeAnalyticsAPIView,
	TeacherChallengeAnalyticsExportAPIView,
	TeacherCourseAnalyticsDetailAPIView,
	TeacherCourseAnalyticsExportAPIView,
	TeacherCourseAnalyticsListAPIView,
	TeacherCourseStudentsAPIView,
	TeacherCourseStudentsExportAPIView,
	TeacherCourseTimelineAPIView,
	TeacherTimelineAPIView,
)
from .api_views import (
	BadgeDetailAPIView,
	BadgeListCreateAPIView,
	ChallengeDetailAPIView,
	ChallengeListCreateAPIView,
	ChallengeParticipantListAPIView,
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
	JoinChallengeAPIView,
	LessonDetailAPIView,
	LessonListCreateAPIView,
	LoginAPIView,
	LogoutAPIView,
	MunicipalityListAPIView,
	MyBadgesAPIView,
	MyCertificatesAPIView,
	MyChallengesAPIView,
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
	ReviewChallengeSubmissionAPIView,
	RoleListAPIView,
	SchoolListAPIView,
	SetChallengeWinnersAPIView,
	StartQuizAttemptAPIView,
	StreakLeaderboardAPIView,
	StudentPointsAPIView,
	StudentQuizAttemptHistoryAPIView,
	StudentQuizDetailAPIView,
	StudentRegistrationAPIView,
	SubjectDetailAPIView,
	SubjectListCreateAPIView,
	SubmitChallengeAPIView,
	SubmitQuizAttemptAPIView,
	TopicDetailAPIView,
	TopicListCreateAPIView,
	VerifyPasswordResetOTPAPIView,
	VerifyPaymentAPIView,
	PointsLeaderboardAPIView,
	RecordShortViewAPIView,
    ShortCommentDetailAPIView,
    ShortCommentListCreateAPIView,
    ShortDetailAPIView,
    ShortListCreateAPIView,
    ToggleShortLikeAPIView,
	AIAskAPIView,
    AIAssistAPIView,
    AIActivityGenerateAPIView,
    AIActivityPendingReviewAPIView,
    AIActivityDetailAPIView,
    AIActivityReviewAPIView,
	AIRecommendationAPIView,
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
	# Badges
	# =========================

	path(
		'badges/',
		BadgeListCreateAPIView.as_view(),
		name='api-badge-list-create'
	),

	path(
		'badges/<int:pk>/',
		BadgeDetailAPIView.as_view(),
		name='api-badge-detail'
	),

	path(
		'my-badges/',
		MyBadgesAPIView.as_view(),
		name='api-my-badges'
	),

	# =========================
	# Challenges
	# =========================

	path(
		'challenges/',
		ChallengeListCreateAPIView.as_view(),
		name='api-challenge-list-create'
	),

	path(
		'challenges/<int:pk>/',
		ChallengeDetailAPIView.as_view(),
		name='api-challenge-detail'
	),

	path(
		'challenges/<int:challenge_id>/join/',
		JoinChallengeAPIView.as_view(),
		name='api-challenge-join'
	),

	path(
		'challenges/<int:challenge_id>/submit/',
		SubmitChallengeAPIView.as_view(),
		name='api-challenge-submit'
	),

	path(
		'challenges/<int:challenge_id>/participants/',
		ChallengeParticipantListAPIView.as_view(),
		name='api-challenge-participants'
	),

	path(
		'challenges/<int:challenge_id>/winners/',
		SetChallengeWinnersAPIView.as_view(),
		name='api-challenge-winners'
	),

	path(
		'challenge-participants/<int:participant_id>/review/',
		ReviewChallengeSubmissionAPIView.as_view(),
		name='api-challenge-review'
	),

	path(
		'my-challenges/',
		MyChallengesAPIView.as_view(),
		name='api-my-challenges'
	),

	# =========================
	# Teacher Analytics
	# =========================

	path(
		'teacher/analytics/courses/',
		TeacherCourseAnalyticsListAPIView.as_view(),
		name='api-teacher-analytics-courses'
	),

	path(
		'teacher/analytics/courses/export/',
		TeacherCourseAnalyticsExportAPIView.as_view(),
		name='api-teacher-analytics-courses-export'
	),

	path(
		'teacher/analytics/courses/<int:course_id>/',
		TeacherCourseAnalyticsDetailAPIView.as_view(),
		name='api-teacher-analytics-course-detail'
	),

	path(
		'teacher/analytics/courses/<int:course_id>/students/',
		TeacherCourseStudentsAPIView.as_view(),
		name='api-teacher-analytics-course-students'
	),

	path(
		'teacher/analytics/courses/<int:course_id>/students/export/',
		TeacherCourseStudentsExportAPIView.as_view(),
		name='api-teacher-analytics-course-students-export'
	),

	path(
		'teacher/analytics/courses/<int:course_id>/timeline/',
		TeacherCourseTimelineAPIView.as_view(),
		name='api-teacher-analytics-course-timeline'
	),

	path(
		'teacher/analytics/timeline/',
		TeacherTimelineAPIView.as_view(),
		name='api-teacher-analytics-timeline'
	),

	path(
		'teacher/analytics/challenges/',
		TeacherChallengeAnalyticsAPIView.as_view(),
		name='api-teacher-analytics-challenges'
	),

	path(
		'teacher/analytics/challenges/export/',
		TeacherChallengeAnalyticsExportAPIView.as_view(),
		name='api-teacher-analytics-challenges-export'
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

	# =========================
# Shorts
# =========================

path(
    'shorts/',
    ShortListCreateAPIView.as_view(),
    name='api-short-list-create',
),

path(
    'shorts/<int:pk>/',
    ShortDetailAPIView.as_view(),
    name='api-short-detail',
),

path(
    'student/shorts/<int:short_id>/view/',
    RecordShortViewAPIView.as_view(),
    name='student-short-view',
),

path(
    'student/shorts/<int:short_id>/like/',
    ToggleShortLikeAPIView.as_view(),
    name='student-short-like',
),

path(
    'student/shorts/<int:short_id>/comments/',
    ShortCommentListCreateAPIView.as_view(),
    name='student-short-comments',
),

path(
    'shorts/comments/<int:pk>/',
    ShortCommentDetailAPIView.as_view(),
    name='short-comment-detail',
),
    	# =========================
	# AI Assistant
	# =========================

	path(
		'ai/ask/',
		AIAskAPIView.as_view(),
		name='ai-ask',
	),

	path(
		'ai/assist/',
		AIAssistAPIView.as_view(),
		name='ai-assist',
	),

	# FR-AI-03 + FR-AI-04
	# Generate activity and save it as pending review
	path(
		'ai/activities/generate/',
		AIActivityGenerateAPIView.as_view(),
		name='ai-activity-generate',
	),

	# FR-AI-04
	# Authorized teacher/admin pending review queue
	path(
		'ai/activities/pending-review/',
		AIActivityPendingReviewAPIView.as_view(),
		name='ai-activity-pending-review',
	),

	# FR-AI-04
	# Student owner or authorized reviewer can view activity
	path(
		'ai/activities/<int:activity_id>/',
		AIActivityDetailAPIView.as_view(),
		name='ai-activity-detail',
	),

	# FR-AI-04
	# Authorized teacher/admin approve or reject activity
	path(
		'ai/activities/<int:activity_id>/review/',
		AIActivityReviewAPIView.as_view(),
		name='ai-activity-review',
	),
	path(
    'ai/recommendations/',
    AIRecommendationAPIView.as_view(),
    name='ai-recommendations'
),
]
