from .bootcamp_views import (CourseResourceListAPIView, CourseResourceDetailAPIView, CourseDiscussionListAPIView, CourseDiscussionDetailAPIView, CourseDiscussionLikeAPIView)
from django.urls import path
from .course_quiz_views import CourseQuizListAPIView
from . import payment_views
from .event_views import (
	EventAdminDetailAPIView, EventAdminListAPIView, EventAdminRegistrationListAPIView,
	EventBookmarkAPIView, EventDetailAPIView, EventListAPIView, EventRegistrationAPIView,
	SavedEventListAPIView,
)
from .advertisement_views import AdvertisementListAPIView, AdvertisementAdminListAPIView, AdvertisementAdminDetailAPIView

from rest_framework_simplejwt.views import TokenRefreshView
from .signup_views import VerifyInstructorSignupOTPAPIView, ResendInstructorSignupOTPAPIView, VerifyStudentSignupOTPAPIView, ResendStudentSignupOTPAPIView
from .learning_interest_views import LearningInterestListAPIView, MyLearningInterestsAPIView, PremiumCategoryListAPIView
from .instructor_analytics import CourseInstructorAnalyticsAPIView, LessonWatchProgressAPIView
from .search_views import RecentSearchesAPIView, SearchAPIView, SearchDiscoverAPIView

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
	HomeFeedAPIView,
	MyLearningAPIView,
	AdminRewardListAPIView,
	AdminRewardDetailAPIView,
	AdminRedemptionListAPIView,
	AdminRedemptionDetailAPIView,
	TopInstructorsAPIView,
	PublicInstructorDetailAPIView,
	InstructorReviewListAPIView,
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
	CompleteStudentProfileAPIView,
	CourseDetailAPIView,
	CourseAssetUploadAPIView,
	CourseReviewListCreateAPIView,
	MyCourseReviewAPIView,
	CourseListCreateAPIView,
	CourseProgressAPIView,
	CurrentUserAPIView,
	DistrictListAPIView,
	EBookListCreateAPIView,
	EBookDetailAPIView,
	EBookContentAPIView,
	BookChaptersAPIView, BookChapterAPIView, BookReorderAPIView, BookImportAPIView,
	BookProgressAPIView, BookBookmarksAPIView, BookBookmarkDetailAPIView,
	ReaderSettingsAPIView, ContinueReadingAPIView,
	BookPDFExtractAPIView,
	EnrollCourseAPIView,
	CourseEnrollmentAPIView,
	ForgotPasswordAPIView,
	GradeListAPIView,
	InitiatePaymentAPIView,
	InstructorCompleteProfileAPIView,
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
	MyDocumentAPIView,
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
	MyRedemptionListAPIView,
	RedeemRewardAPIView,
	RewardListAPIView,
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
	ShortCommentRepliesAPIView,
	ToggleShortCommentLikeAPIView,
	ShortDetailAPIView,
	ShortListCreateAPIView,
	StudentShortBookmarkAPIView,
	SavedShortsListAPIView,
	ToggleShortLikeAPIView,
	NotificationListAPIView,
	NotificationUnreadCountAPIView,
	NotificationMarkReadAPIView,
	NotificationMarkAllReadAPIView,
	AIAskAPIView,
	AIAssistAPIView,
	AIActivityGenerateAPIView,
	AIActivityPendingReviewAPIView,
	AIActivityDetailAPIView,
	AIActivityReviewAPIView,
	AIRecommendationAPIView,
	MunicipalityDashboardAPIView,
	MinistryDashboardAPIView,
	SuperAdminUserListAPIView,
	SuperAdminUserDetailAPIView,
	SuperAdminUserStatusAPIView,
	SuperAdminUserRoleAPIView,
	SuperAdminInstructorVerificationAPIView,
	SuperAdminUserDocumentAPIView,
	SuperAdminPermissionListAPIView,
	SuperAdminRolePermissionListAPIView,
	SuperAdminRolePermissionDetailAPIView,
	SuperAdminAuditLogListAPIView,
	SuperAdminAuditLogDetailAPIView,
)


from .book_commerce_api import (
	BookOrderDetailView, BookOrdersView, BookReviewDetailView, BookReviewsView,
	BuyBookView, GetFreeBookView, MyBooksView, SaveBookView, SavedBooksView,
)

urlpatterns = [
    path('courses/<int:course_id>/resources/', CourseResourceListAPIView.as_view(), name='api-course-resources'),
    path('courses/<int:course_id>/resources/<int:resource_id>/', CourseResourceDetailAPIView.as_view(), name='api-course-resource-detail'),
    path('courses/<int:course_id>/discussions/', CourseDiscussionListAPIView.as_view(), name='api-course-discussions'),
    path('courses/<int:course_id>/discussions/<int:discussion_id>/', CourseDiscussionDetailAPIView.as_view(), name='api-course-discussion-detail'),
    path('courses/<int:course_id>/discussions/<int:discussion_id>/like/', CourseDiscussionLikeAPIView.as_view(), name='api-course-discussion-like'),
	path('courses/<int:course_id>/quizzes/', CourseQuizListAPIView.as_view(), name='api-course-quizzes'),
    # Browser pages inside the Khalti / eSewa flow (opened in the app's WebView).
    path('payments/esewa/checkout/<str:reference>/', payment_views.esewa_checkout, name='payment-esewa-checkout'),
    path('payments/esewa/return/<str:reference>/', payment_views.esewa_return, name='payment-esewa-return'),
    path('payments/khalti/return/<str:reference>/', payment_views.khalti_return, name='payment-khalti-return'),
    path('payments/complete/<str:reference>/', payment_views.payment_complete, name='payment-complete'),
	path('admin/rewards/', AdminRewardListAPIView.as_view(), name='api-admin-rewards'),
	path('admin/rewards/<int:reward_id>/', AdminRewardDetailAPIView.as_view(), name='api-admin-reward-detail'),
	path('admin/redemptions/', AdminRedemptionListAPIView.as_view(), name='api-admin-redemptions'),
	path('admin/redemptions/<int:redemption_id>/', AdminRedemptionDetailAPIView.as_view(), name='api-admin-redemption-detail'),
	path('home/', HomeFeedAPIView.as_view(), name='api-home'),
	path('my-learning/', MyLearningAPIView.as_view(), name='api-my-learning'),
    path('events/', EventListAPIView.as_view(), name='api-events'),
    path('events/saved/', SavedEventListAPIView.as_view(), name='api-events-saved'),
    path('events/<int:event_id>/', EventDetailAPIView.as_view(), name='api-event-detail'),
    path('events/<int:event_id>/register/', EventRegistrationAPIView.as_view(), name='api-event-register'),
    path('events/<int:event_id>/save/', EventBookmarkAPIView.as_view(), name='api-event-save'),
    path('admin/events/', EventAdminListAPIView.as_view(), name='api-admin-events'),
    path('admin/events/<int:event_id>/', EventAdminDetailAPIView.as_view(), name='api-admin-event-detail'),
    path('admin/events/<int:event_id>/registrations/', EventAdminRegistrationListAPIView.as_view(), name='api-admin-event-registrations'),
	path('instructors/top/', TopInstructorsAPIView.as_view(), name='api-top-instructors'),
	path('instructors/<int:instructor_id>/', PublicInstructorDetailAPIView.as_view(), name='api-public-instructor-detail'),
	path('instructors/<int:instructor_id>/reviews/', InstructorReviewListAPIView.as_view(), name='api-instructor-reviews'),
    path('advertisements/', AdvertisementListAPIView.as_view(), name='api-advertisements'),
    path('admin/advertisements/', AdvertisementAdminListAPIView.as_view(), name='api-admin-advertisements'),
    path('admin/advertisements/<int:advertisement_id>/', AdvertisementAdminDetailAPIView.as_view(), name='api-admin-advertisement-detail'),
	path('learning-interests/', LearningInterestListAPIView.as_view(), name='api-learning-interests'),
	# The premium course's own category list — never the skill one above.
	path('premium-categories/', PremiumCategoryListAPIView.as_view(), name='api-premium-categories'),
	path('me/learning-interests/', MyLearningInterestsAPIView.as_view(), name='api-my-learning-interests'),
	path('register/instructor/verify-otp/', VerifyInstructorSignupOTPAPIView.as_view(), name='api-instructor-signup-verify'),
	path('register/student/verify-otp/', VerifyStudentSignupOTPAPIView.as_view(), name='api-student-signup-verify'),
	path('register/student/resend-otp/', ResendStudentSignupOTPAPIView.as_view(), name='api-student-signup-resend'),
	path('register/instructor/resend-otp/', ResendInstructorSignupOTPAPIView.as_view(), name='api-instructor-signup-resend'),
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
		'me/documents/<int:document_id>/',
		MyDocumentAPIView.as_view(),
		name='api-my-document'
	),

	path(
		'me/complete-profile/',
		CompleteStudentProfileAPIView.as_view(),
		name='api-complete-student-profile'
	),

	path(
		'instructor/complete-profile/',
		InstructorCompleteProfileAPIView.as_view(),
		name='api-instructor-complete-profile'
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
		'courses/<int:course_id>/reviews/',
		CourseReviewListCreateAPIView.as_view(),
		name='api-course-reviews',
	),
	path(
		'courses/<int:course_id>/reviews/me/',
		MyCourseReviewAPIView.as_view(),
		name='api-my-course-review',
	),

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

	# Cover image and lesson files. Course-scoped because a lesson's video is
	# uploaded before the lesson row exists.
	path(
		'courses/<int:course_id>/assets/',
		CourseAssetUploadAPIView.as_view(),
		name='api-course-asset-upload'
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
		'courses/<int:course_id>/enrollment/',
		CourseEnrollmentAPIView.as_view(),
		name='api-course-enrollment'
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

	path(
		'lessons/<int:lesson_id>/progress/',
		LessonWatchProgressAPIView.as_view(),
		name='api-lesson-watch-progress'
	),

	path(
		'courses/<int:course_id>/instructor-analytics/',
		CourseInstructorAnalyticsAPIView.as_view(),
		name='api-course-instructor-analytics'
	),

	# =========================
	# Search
	# =========================

	path('search/', SearchAPIView.as_view(), name='api-search'),
	path('search/discover/', SearchDiscoverAPIView.as_view(), name='api-search-discover'),
	path('search/recent/', RecentSearchesAPIView.as_view(), name='api-search-recent'),

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
	# Shorts
	# =========================
	path('student/shorts/saved/', SavedShortsListAPIView.as_view(), name='student-saved-shorts'),
	path('student/shorts/<int:short_id>/save/', StudentShortBookmarkAPIView.as_view(), name='student-short-save'),

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

	path(
		'shorts/comments/<int:pk>/replies/',
		ShortCommentRepliesAPIView.as_view(),
		name='short-comment-replies',
	),

	path(
		'shorts/comments/<int:pk>/like/',
		ToggleShortCommentLikeAPIView.as_view(),
		name='short-comment-like',
	),

	# =========================
	# eBooks
	# =========================

	path(
		'ebooks/',
		EBookListCreateAPIView.as_view(),
		name='api-ebook-list-create'
	),

	path(
		'ebooks/<int:pk>/',
		EBookDetailAPIView.as_view(),
		name='api-ebook-detail'
	),
	path('ebooks/saved/', SavedBooksView.as_view(), name='api-book-saved'),
	path('ebooks/my-books/', MyBooksView.as_view(), name='api-book-library'),
	path('ebooks/<int:book_id>/save/', SaveBookView.as_view(), name='api-book-save'),
	path('ebooks/<int:book_id>/reviews/', BookReviewsView.as_view(), name='api-book-reviews'),
	path('ebooks/<int:book_id>/reviews/<int:review_id>/', BookReviewDetailView.as_view(), name='api-book-review'),
	path('ebooks/<int:book_id>/buy/', BuyBookView.as_view(), name='api-book-buy'),
	path('ebooks/<int:book_id>/get-free/', GetFreeBookView.as_view(), name='api-book-get-free'),
	path('book-orders/', BookOrdersView.as_view(), name='api-book-orders'),
	path('book-orders/<int:pk>/', BookOrderDetailView.as_view(), name='api-book-order'),
	path('ebooks/<int:pk>/content/', EBookContentAPIView.as_view(), name='api-ebook-content'),
	path('ebooks/<int:book_id>/chapters/', BookChaptersAPIView.as_view(), name='api-book-chapters'),
	path('ebooks/<int:book_id>/chapters/<int:chapter_id>/', BookChapterAPIView.as_view(), name='api-book-chapter'),
	path('ebooks/<int:book_id>/chapters/<int:chapter_id>/extract-pdf/', BookPDFExtractAPIView.as_view(), name='api-book-pdf-extract'),
	path('ebooks/<int:book_id>/chapters/reorder/', BookReorderAPIView.as_view(), name='api-book-reorder'),
	path('ebooks/<int:book_id>/import-epub/', BookImportAPIView.as_view(), name='api-book-import'),
	path('ebooks/<int:book_id>/progress/', BookProgressAPIView.as_view(), name='api-book-progress'),
	path('ebooks/<int:book_id>/bookmarks/', BookBookmarksAPIView.as_view(), name='api-book-bookmarks'),
	path('ebooks/<int:book_id>/bookmarks/<int:bookmark_id>/', BookBookmarkDetailAPIView.as_view(), name='api-book-bookmark'),
	path('reader/settings/', ReaderSettingsAPIView.as_view(), name='api-reader-settings'),
	path('reader/continue/', ContinueReadingAPIView.as_view(), name='api-reader-continue'),

	# =========================
	# Notifications
	# =========================

	path(
		'notifications/',
		NotificationListAPIView.as_view(),
		name='notification-list',
	),

	path(
		'notifications/unread-count/',
		NotificationUnreadCountAPIView.as_view(),
		name='notification-unread-count',
	),

	path(
		'notifications/<int:pk>/read/',
		NotificationMarkReadAPIView.as_view(),
		name='notification-mark-read',
	),

	path(
		'notifications/mark-all-read/',
		NotificationMarkAllReadAPIView.as_view(),
		name='notification-mark-all-read',
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

	path(
		'ai/activities/generate/',
		AIActivityGenerateAPIView.as_view(),
		name='ai-activity-generate',
	),

	path(
		'ai/activities/pending-review/',
		AIActivityPendingReviewAPIView.as_view(),
		name='ai-activity-pending-review',
	),

	path(
		'ai/activities/<int:activity_id>/',
		AIActivityDetailAPIView.as_view(),
		name='ai-activity-detail',
	),

	path(
		'ai/activities/<int:activity_id>/review/',
		AIActivityReviewAPIView.as_view(),
		name='ai-activity-review',
	),

	path(
		'ai/recommendations/',
		AIRecommendationAPIView.as_view(),
		name='ai-recommendations',
	),

	# =========================
	# Municipality / Ministry Dashboards
	# =========================

	path(
		'municipality/dashboard/',
		MunicipalityDashboardAPIView.as_view(),
		name='api-municipality-dashboard',
	),

	path(
		'ministry/dashboard/',
		MinistryDashboardAPIView.as_view(),
		name='api-ministry-dashboard',
	),

	# =========================
	# Super Admin - User Management
	# =========================

	path(
		'admin/users/',
		SuperAdminUserListAPIView.as_view(),
		name='api-admin-users'
	),

	path(
		'admin/users/<int:user_id>/',
		SuperAdminUserDetailAPIView.as_view(),
		name='api-admin-user-detail'
	),

	path(
		'admin/users/<int:user_id>/documents/<int:document_id>/',
		SuperAdminUserDocumentAPIView.as_view(),
		name='api-admin-user-document'
	),

	path(
		'admin/users/<int:user_id>/status/',
		SuperAdminUserStatusAPIView.as_view(),
		name='api-admin-user-status'
	),

	path(
		'admin/users/<int:user_id>/role/',
		SuperAdminUserRoleAPIView.as_view(),
		name='api-admin-user-role'
	),

	path(
		'admin/instructors/<int:user_id>/verification/',
		SuperAdminInstructorVerificationAPIView.as_view(),
		name='api-admin-instructor-verification'
	),

	# =========================
	# Super Admin - Role & Permission Management
	# =========================

	path(
		'admin/permissions/',
		SuperAdminPermissionListAPIView.as_view(),
		name='api-admin-permissions'
	),

	path(
		'admin/roles/',
		SuperAdminRolePermissionListAPIView.as_view(),
		name='api-admin-roles'
	),

	path(
		'admin/roles/<int:role_id>/permissions/',
		SuperAdminRolePermissionDetailAPIView.as_view(),
		name='api-admin-role-permissions'
	),

	path(
		'admin/audit-logs/',
		SuperAdminAuditLogListAPIView.as_view(),
		name='api-admin-audit-logs'
	),

	path(
		'admin/audit-logs/<int:audit_log_id>/',
		SuperAdminAuditLogDetailAPIView.as_view(),
		name='api-admin-audit-log-detail'
	),

        # =========================
        # Rewards & Redemption
        # =========================

        path(
                'rewards/',
                RewardListAPIView.as_view(),
                name='api-rewards'
        ),

        path(
                'rewards/redeem/',
                RedeemRewardAPIView.as_view(),
                name='api-redeem-reward'
        ),

        path(
                'redemptions/',
                MyRedemptionListAPIView.as_view(),
                name='api-my-redemptions'
        ),

]
