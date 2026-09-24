from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from django.db.models import Sum, Count, Avg

from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied, NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers


from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
	Badge,
	Certificate,
	CertificateCriteria,
	Challenge,
	ChallengeParticipant,
	Chapter,
	Course,
	District,
	EBook,
	Enrollment,
	Grade,
	LearningStreak,
	Lesson,
	LessonProgress,
	Municipality,
	Payment,
	Province,
	Question,
	QuestionOption,
	Quiz,
	QuizAttempt,
	School,
	StreakHistory,
	StreakSettings,
	StudentAnswer,
	StudentBadge,
	Subject,
	Topic,
	User,
	PointTransaction,
	Short,
	ShortComment,
	ShortLike,
	ShortView,
	Notification,
	AIActivity,
	LocalAuthorityProfile,
	Role,
	Permission,
	RolePermission,
	AuditLog,
)

from .ai_service import GeminiService

from .serializers import (
	BadgeSerializer,
	CertificateSerializer,
	ChallengeParticipantSerializer,
	ChallengeReviewSerializer,
	ChallengeSerializer,
	ChallengeSubmitSerializer,
	ChallengeWinnersSerializer,
	ChapterSerializer,
	CompleteStudentProfileSerializer,
	CourseSerializer,
	DistrictSerializer,
	EBookSerializer,
	EnrollCourseSerializer,
	EnrollmentSerializer,
	ForgotPasswordSerializer,
	GradeSerializer,
	InitiatePaymentSerializer,
	InstructorQuizResultSerializer,
	InstructorRegistrationSerializer,
	LeaderboardEntrySerializer,
	LearningStreakSerializer,
	LessonProgressSerializer,
	LessonSerializer,
	LoginSerializer,
	MunicipalitySerializer,
	PaymentSerializer,
	ProvinceSerializer,
	QuestionManagementSerializer,
	QuestionOptionManagementSerializer,
	QuizAttemptSerializer,
	QuizManagementSerializer,
	QuizStudentSerializer,
	QuizSubmitSerializer,
	ResetPasswordSerializer,
	SchoolSerializer,
	StudentBadgeSerializer,
	StudentRegistrationSerializer,
	SubjectSerializer,
	TopicSerializer,
	VerifyPasswordResetOTPSerializer,
	VerifyPaymentSerializer,
	PointsLeaderboardEntrySerializer,
	PointTransactionSerializer,
	ShortCommentSerializer,
	ShortLikeSerializer,
	ShortSerializer,
	ShortViewSerializer,
	NotificationSerializer,
)


# =========================================================
# Registration
# =========================================================

class RegistrationResponseMixin:
	serializer_class = None
	role_name = None

	def post(self, request, *args, **kwargs):
		serializer = self.serializer_class(data=request.data)

		if not serializer.is_valid():
			email_errors = serializer.errors.get('email', [])

			if any(
				getattr(error, 'code', None) == 'EMAIL_ALREADY_REGISTERED'
				for error in email_errors
			):
				return Response(
					{
						'code': 'EMAIL_ALREADY_REGISTERED',
						'message': 'A user with this email already exists.',
						'errors': serializer.errors,
					},
					status=status.HTTP_400_BAD_REQUEST,
				)

			return Response(
				serializer.errors,
				status=status.HTTP_400_BAD_REQUEST,
			)

		user = serializer.save()
		refresh = RefreshToken.for_user(user)

		return Response(
			{
				'user': {
					'id': str(user.id),
					'email': user.email,
					'name': user.name,
					'role': self.role_name,
					'verification_status': user.verification_status,
				},
				'tokens': {
					'refresh': str(refresh),
					'access': str(refresh.access_token),
				},
			},
			status=status.HTTP_201_CREATED,
		)


class StudentRegistrationAPIView(
	RegistrationResponseMixin,
	APIView
):
	serializer_class = StudentRegistrationSerializer
	role_name = 'student'
	parser_classes = [JSONParser, FormParser, MultiPartParser]


class InstructorRegistrationAPIView(
	RegistrationResponseMixin,
	APIView
):
	serializer_class = InstructorRegistrationSerializer
	role_name = 'instructor'
	parser_classes = [JSONParser, FormParser, MultiPartParser]


# =========================================================
# Authentication
# =========================================================

class LoginAPIView(APIView):
	def post(self, request):
		serializer = LoginSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		user = serializer.validated_data['user']
		refresh = RefreshToken.for_user(user)

		return Response(
			{
				'user': {
					'id': str(user.id),
					'email': user.email,
					'name': user.name,
					'role': user.role.name if user.role else None,
					'verification_status': user.verification_status,
				},
				'tokens': {
					'refresh': str(refresh),
					'access': str(refresh.access_token),
				},
			},
			status=status.HTTP_200_OK,
		)


class CurrentUserAPIView(APIView):
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		user = request.user

		return Response(
			{
				'id': str(user.id),
				'email': user.email,
				'name': user.name,
				'role': user.role.name if user.role else None,
				'verification_status': user.verification_status,
				'onboarding_completed': user.onboarding_completed,
				'is_active': user.is_active,
			},
			status=status.HTTP_200_OK,
		)


class LogoutAPIView(APIView):
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		refresh_token = request.data.get('refresh')

		if not refresh_token:
			return Response(
				{'detail': 'Refresh token is required.'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		try:
			token = RefreshToken(refresh_token)
			token.blacklist()

			return Response(
				{'detail': 'Logged out successfully.'},
				status=status.HTTP_200_OK,
			)

		except TokenError:
			return Response(
				{'detail': 'Invalid or expired refresh token.'},
				status=status.HTTP_400_BAD_REQUEST,
			)


# =========================================================
# Password Reset
# =========================================================

class ForgotPasswordAPIView(APIView):
	def post(self, request):
		serializer = ForgotPasswordSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		serializer.save()

		return Response(
			{
				'detail': (
					'If an account exists with this email, '
					'a password reset OTP has been sent.'
				)
			},
			status=status.HTTP_200_OK,
		)


class VerifyPasswordResetOTPAPIView(APIView):
	def post(self, request):
		serializer = VerifyPasswordResetOTPSerializer(
			data=request.data
		)

		serializer.is_valid(raise_exception=True)

		return Response(
			{
				'detail': 'OTP verified successfully.',
				'reset_token': serializer.validated_data['reset_token'],
			},
			status=status.HTTP_200_OK,
		)


class ResetPasswordAPIView(APIView):
	def post(self, request):
		serializer = ResetPasswordSerializer(data=request.data)

		serializer.is_valid(raise_exception=True)
		serializer.save()

		return Response(
			{'detail': 'Password reset successfully.'},
			status=status.HTTP_200_OK,
		)


# =========================================================
# Roles
# =========================================================

class RoleListAPIView(APIView):
	def get(self, request):
		return Response(
			[
				{
					'value': 'student',
					'label': 'Student',
				},
				{
					'value': 'instructor',
					'label': 'Instructor',
				},
			]
		)


# =========================================================
# Lookup APIs
# =========================================================

class LookupListAPIView(generics.ListAPIView):
	lookup_model = None
	serializer_class = None

	def get_queryset(self) -> QuerySet:
		queryset = self.lookup_model.objects.all()

		if (
			self.lookup_model is District
			and self.request.query_params.get('province_id')
		):
			queryset = queryset.filter(
				province_id=self.request.query_params['province_id']
			)

		elif (
			self.lookup_model is Municipality
			and self.request.query_params.get('district_id')
		):
			queryset = queryset.filter(
				district_id=self.request.query_params['district_id']
			)

		elif (
			self.lookup_model is School
			and self.request.query_params.get('municipality_id')
		):
			queryset = queryset.filter(
				municipality_id=self.request.query_params[
					'municipality_id'
				]
			)

		return queryset.order_by('name')


class ProvinceListAPIView(LookupListAPIView):
	lookup_model = Province
	serializer_class = ProvinceSerializer


class DistrictListAPIView(LookupListAPIView):
	lookup_model = District
	serializer_class = DistrictSerializer


class MunicipalityListAPIView(LookupListAPIView):
	lookup_model = Municipality
	serializer_class = MunicipalitySerializer


class SchoolListAPIView(LookupListAPIView):
	lookup_model = School
	serializer_class = SchoolSerializer


class GradeListAPIView(LookupListAPIView):
	lookup_model = Grade
	serializer_class = GradeSerializer


# =========================================================
# Course Permission Helpers
# =========================================================

def _role_name(user):
	return getattr(
		getattr(user, 'role', None),
		'name',
		''
	)


def _is_admin(user):
	return (
		user.is_superuser
		or _role_name(user) == 'super_admin'
	)


def _is_instructor(user):
	return _role_name(user) == 'instructor'


def _is_student(user):
	return _role_name(user) == 'student'


def _is_verified_instructor(user):
	return (
		_is_instructor(user)
		and user.verification_status == 'verified'
	)


# =========================================================
# Streak Helper
# =========================================================

def _update_streak(student):
	today = timezone.now().date()

	_, created_today = StreakHistory.objects.get_or_create(student=student, date=today)
	if not created_today:
		return

	streak, _ = LearningStreak.objects.get_or_create(student=student)
	settings_row = StreakSettings.get_solo()
	grace = settings_row.grace_period_days

	if streak.last_active_date is None:
		streak.current_streak = 1
	else:
		gap = (today - streak.last_active_date).days
		if gap <= 1 + grace:
			streak.current_streak += 1
		else:
			streak.current_streak = 1

	streak.longest_streak = max(streak.longest_streak, streak.current_streak)
	streak.last_active_date = today
	streak.save(update_fields=['current_streak', 'longest_streak', 'last_active_date'])


# =========================================================
# Certificate Eligibility Helpers
# =========================================================

def _check_course_certificate_eligibility(student, course):
	enrollment = Enrollment.objects.filter(student=student, course=course, status='completed').first()
	if enrollment is None:
		return False

	criteria = CertificateCriteria.get_solo()
	if criteria.skill_course_requires_quiz_pass:
		course_quizzes = Quiz.objects.filter(course=course, is_published=True)
		for quiz in course_quizzes:
			has_passed = QuizAttempt.objects.filter(student=student, quiz=quiz, is_passed=True).exists()
			if not has_passed:
				return False

	return True


def _check_grade_certificate_eligibility(student, grade):
	academic_courses = Course.objects.filter(course_type='academic', grade=grade, is_published=True)
	if not academic_courses.exists():
		return False

	criteria = CertificateCriteria.get_solo()
	total_percentage = 0
	course_count = 0

	for course in academic_courses:
		total_lessons = Lesson.objects.filter(course=course).count()
		if total_lessons == 0:
			continue
		completed_lessons = LessonProgress.objects.filter(
			student=student, lesson__course=course, is_completed=True,
		).count()
		total_percentage += (completed_lessons / total_lessons) * 100
		course_count += 1

	if course_count == 0:
		return False

	average_percentage = total_percentage / course_count
	return average_percentage >= criteria.academic_grade_min_completion_percentage


# =========================================================
# Badge Helpers
# =========================================================

def _count_perfect_quizzes(student):
	return QuizAttempt.objects.filter(
		student=student,
		completed_at__isnull=False,
		percentage__gte=Decimal('100'),
	).order_by().values('quiz_id').distinct().count()


def _count_completed_courses(student):
	course_ids = LessonProgress.objects.filter(
		student=student,
		is_completed=True,
		lesson__course__isnull=False,
	).order_by().values_list('lesson__course_id', flat=True).distinct()

	completed_courses = 0

	for course_id in course_ids:
		total_lessons = Lesson.objects.filter(course_id=course_id).count()
		completed_lessons = LessonProgress.objects.filter(
			student=student,
			lesson__course_id=course_id,
			is_completed=True,
		).count()

		if total_lessons > 0 and completed_lessons == total_lessons:
			completed_courses += 1

	return completed_courses


def _check_and_award_badges(student):
	already_earned = StudentBadge.objects.filter(
		student=student
	).values_list('badge_id', flat=True)

	pending_badges = list(
		Badge.objects.filter(
			is_active=True
		).exclude(
			id__in=already_earned
		)
	)

	if not pending_badges:
		return []

	progress = {}
	awarded = []

	for badge in pending_badges:
		criteria_type = badge.criteria_type

		if criteria_type not in progress:
			if criteria_type == 'quiz_perfect_score':
				progress[criteria_type] = _count_perfect_quizzes(student)

			elif criteria_type == 'streak_milestone':
				streak = LearningStreak.objects.filter(student=student).first()
				progress[criteria_type] = streak.longest_streak if streak else 0

			elif criteria_type == 'course_completion_count':
				progress[criteria_type] = _count_completed_courses(student)

			else:
				progress[criteria_type] = 0

		if progress[criteria_type] >= badge.criteria_value:
			_, created = StudentBadge.objects.get_or_create(
				student=student,
				badge=badge,
			)

			if created:
				awarded.append(badge)

	return awarded


# =========================================================
# Subject Management
# =========================================================

class SubjectListCreateAPIView(generics.ListCreateAPIView):
	serializer_class = SubjectSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		return Subject.objects.all().order_by('name')

	def perform_create(self, serializer):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can create subjects.'
			)

		serializer.save()


class SubjectDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	serializer_class = SubjectSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]
	queryset = Subject.objects.all()

	def perform_update(self, serializer):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can update subjects.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can delete subjects.'
			)

		instance.delete()


# =========================================================
# Chapter Management
# =========================================================

class ChapterListCreateAPIView(generics.ListCreateAPIView):
	serializer_class = ChapterSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		queryset = Chapter.objects.select_related(
			'subject',
			'grade',
		)

		subject_id = self.request.query_params.get('subject')
		grade_id = self.request.query_params.get('grade')

		if subject_id:
			queryset = queryset.filter(
				subject_id=subject_id
			)

		if grade_id:
			queryset = queryset.filter(
				grade_id=grade_id
			)

		return queryset.order_by('order', 'name')

	def perform_create(self, serializer):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can create chapters.'
			)

		serializer.save()


class ChapterDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	serializer_class = ChapterSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	queryset = Chapter.objects.select_related(
		'subject',
		'grade',
	)

	def perform_update(self, serializer):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can update chapters.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can delete chapters.'
			)

		instance.delete()


# =========================================================
# Topic Management
# =========================================================

class TopicListCreateAPIView(generics.ListCreateAPIView):
	serializer_class = TopicSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		queryset = Topic.objects.select_related(
			'chapter',
			'chapter__subject',
			'chapter__grade',
		)

		chapter_id = self.request.query_params.get('chapter')

		if chapter_id:
			queryset = queryset.filter(
				chapter_id=chapter_id
			)

		return queryset.order_by('order', 'name')

	def perform_create(self, serializer):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can create topics.'
			)

		serializer.save()


class TopicDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	serializer_class = TopicSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	queryset = Topic.objects.select_related(
		'chapter',
		'chapter__subject',
		'chapter__grade',
	)

	def perform_update(self, serializer):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can update topics.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can delete topics.'
			)

		instance.delete()


# =========================================================
# Course Management
# =========================================================

class CourseListCreateAPIView(generics.ListCreateAPIView):
	serializer_class = CourseSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		queryset = Course.objects.select_related(
			'instructor',
			'subject',
			'grade',
		)

		user = self.request.user

		if _is_admin(user):
			pass

		elif _is_instructor(user):
			queryset = queryset.filter(
				Q(is_published=True) |
				Q(instructor=user)
			)

		else:
			queryset = queryset.filter(
				is_published=True
			)

		course_type = self.request.query_params.get(
			'course_type'
		)
		subject_id = self.request.query_params.get(
			'subject'
		)
		grade_id = self.request.query_params.get(
			'grade'
		)
		is_paid = self.request.query_params.get(
			'is_paid'
		)
		instructor_id = self.request.query_params.get(
			'instructor'
		)
		is_published = self.request.query_params.get(
			'is_published'
		)

		if course_type:
			queryset = queryset.filter(
				course_type=course_type
			)

		if subject_id:
			queryset = queryset.filter(
				subject_id=subject_id
			)

		if grade_id:
			queryset = queryset.filter(
				grade_id=grade_id
			)

		if instructor_id:
			queryset = queryset.filter(
				instructor_id=instructor_id
			)

		if is_paid is not None:
			if is_paid.lower() == 'true':
				queryset = queryset.filter(
					is_paid=True
				)

			elif is_paid.lower() == 'false':
				queryset = queryset.filter(
					is_paid=False
				)

		if is_published is not None:
			if is_published.lower() == 'true':
				queryset = queryset.filter(
					is_published=True
				)

			elif is_published.lower() == 'false':
				queryset = queryset.filter(
					is_published=False
				)

		return queryset.order_by('-created_at')

	def perform_create(self, serializer):
		if not _is_instructor(self.request.user):
			raise PermissionDenied(
				'Only instructors can create courses.'
			)

		serializer.save(
			instructor=self.request.user,
			is_published=False,
		)


class CourseDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	serializer_class = CourseSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		queryset = Course.objects.select_related(
			'instructor',
			'subject',
			'grade',
		)

		user = self.request.user

		if _is_admin(user):
			return queryset

		if _is_instructor(user):
			return queryset.filter(
				Q(is_published=True)
				| Q(instructor=user)
			)

		return queryset.filter(
			is_published=True
		)

	def _check_owner_or_admin(self, course):
		user = self.request.user

		if not (
			_is_admin(user)
			or course.instructor_id == user.id
		):
			raise PermissionDenied(
				'Only the course owner or administrator '
				'can modify this course.'
			)

	def perform_update(self, serializer):
		course = self.get_object()
		self._check_owner_or_admin(course)

		requested_publish = serializer.validated_data.get(
			'is_published',
			course.is_published,
		)

		if (
			requested_publish
			and not course.is_published
			and not _is_admin(self.request.user)
			and not _is_verified_instructor(
				self.request.user
			)
		):
			raise PermissionDenied(
				'Only verified instructors can publish courses.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		self._check_owner_or_admin(instance)
		instance.delete()


# =========================================================
# Lesson Management
# =========================================================

class LessonListCreateAPIView(generics.ListCreateAPIView):
	serializer_class = LessonSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		queryset = Lesson.objects.select_related(
			'topic',
			'topic__chapter',
			'course',
			'course__instructor',
		)

		topic_id = self.request.query_params.get(
			'topic'
		)
		course_id = self.request.query_params.get(
			'course'
		)

		if topic_id:
			queryset = queryset.filter(
				topic_id=topic_id
			)

		if course_id:
			queryset = queryset.filter(
				course_id=course_id
			)

		return queryset.order_by('order', 'title')

	def perform_create(self, serializer):
		user = self.request.user
		course = serializer.validated_data.get('course')

		if not (
			_is_instructor(user)
			or _is_admin(user)
		):
			raise PermissionDenied(
				'Only instructors or administrators '
				'can create lessons.'
			)

		if not _is_admin(user):
			if course.instructor_id != user.id:
				raise PermissionDenied(
					'You cannot add lessons to another '
					"instructor's course."
				)

		serializer.save()


class LessonDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	serializer_class = LessonSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		return Lesson.objects.select_related(
			'topic',
			'topic__chapter',
			'course',
			'course__instructor',
		)

	def _check_permission(self, lesson):
		user = self.request.user

		if _is_admin(user):
			return

		if (
			lesson.course
			and lesson.course.instructor_id == user.id
		):
			return

		raise PermissionDenied(
			'You do not have permission to modify this lesson.'
		)

	def perform_update(self, serializer):
		lesson = self.get_object()
		self._check_permission(lesson)

		new_course = serializer.validated_data.get(
			'course',
			lesson.course,
		)

		if (
			not _is_admin(self.request.user)
			and new_course.instructor_id != self.request.user.id
		):
			raise PermissionDenied(
				'You cannot move this lesson to another '
				"instructor's course."
			)

		serializer.save()

	def perform_destroy(self, instance):
		self._check_permission(instance)
		instance.delete()


# =========================================================
# Enrollment & Progress
# =========================================================

class EnrollCourseAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request, course_id):
		course = Course.objects.filter(pk=course_id).first()
		if course is None:
			return Response({'detail': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)

		serializer = EnrollCourseSerializer(data={}, context={'course': course, 'request': request})
		serializer.is_valid(raise_exception=True)
		enrollment = serializer.save()

		return Response(
			EnrollmentSerializer(enrollment).data,
			status=status.HTTP_201_CREATED,
		)


class MyEnrollmentsAPIView(generics.ListAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = EnrollmentSerializer

	def get_queryset(self):
		return Enrollment.objects.filter(
			student=self.request.user
		).select_related('course').order_by('-enrolled_at')


class CompleteLessonAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request, lesson_id):
		lesson = Lesson.objects.filter(pk=lesson_id).select_related(
			'course', 'topic__chapter'
		).first()

		if lesson is None:
			return Response({'detail': 'Lesson not found.'}, status=status.HTTP_404_NOT_FOUND)

		student = request.user
		enrollment = None

		if lesson.course is not None:
			has_access = Enrollment.objects.filter(
				student=student,
				course=lesson.course,
				status__in=['active', 'completed'],
			).exists()

			if not has_access:
				return Response(
					{'detail': 'You must be enrolled in this course to access this lesson.'},
					status=status.HTTP_403_FORBIDDEN,
				)

			enrollment = Enrollment.objects.filter(
				student=student, course=lesson.course
			).first()

		elif lesson.topic is not None:
			student_grade_id = getattr(
				getattr(student, 'student_profile', None), 'grade_id', None
			)

			if student_grade_id != lesson.topic.chapter.grade_id:
				return Response(
					{'detail': 'This lesson is not part of your grade.'},
					status=status.HTTP_403_FORBIDDEN,
				)

		else:
			return Response(
				{'detail': 'This lesson is not attached to any course or topic.'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		progress, _ = LessonProgress.objects.update_or_create(
			student=student,
			lesson=lesson,
			defaults={
				'enrollment': enrollment,
				'is_completed': True,
				'completed_at': timezone.now(),
			},
		)

		_update_streak(student)
		_check_and_award_badges(student)

		return Response(LessonProgressSerializer(progress).data, status=status.HTTP_200_OK)


class CourseProgressAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request, course_id):
		course = Course.objects.filter(pk=course_id).first()
		if course is None:
			return Response({'detail': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)

		student = request.user

		enrollment = Enrollment.objects.filter(
			student=student, course=course, status__in=['active', 'completed'],
		).first()

		if enrollment is None:
			return Response(
				{'detail': 'You must be enrolled in this course to view progress.'},
				status=status.HTTP_403_FORBIDDEN,
			)

		total_lessons = Lesson.objects.filter(course=course).count()
		completed_lessons = LessonProgress.objects.filter(
			student=student, lesson__course=course, is_completed=True,
		).count()

		progress_percentage = round((completed_lessons / total_lessons) * 100, 2) if total_lessons > 0 else 0.0
		is_completed = total_lessons > 0 and completed_lessons == total_lessons

		if is_completed and enrollment.status != 'completed':
			enrollment.status = 'completed'
			enrollment.completed_at = timezone.now()
			enrollment.save(update_fields=['status', 'completed_at'])

		return Response({
			'course_id': course.id,
			'total_lessons': total_lessons,
			'completed_lessons': completed_lessons,
			'progress_percentage': progress_percentage,
			'is_completed': is_completed,
		}, status=status.HTTP_200_OK)


# =========================================================
# Payment
# =========================================================

class InitiatePaymentAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request, course_id):
		course = Course.objects.filter(pk=course_id).first()
		if course is None:
			return Response({'detail': 'Course not found.'}, status=status.HTTP_404_NOT_FOUND)

		serializer = InitiatePaymentSerializer(data=request.data, context={'course': course, 'request': request})
		serializer.is_valid(raise_exception=True)
		payment = serializer.save()

		return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class VerifyPaymentAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		serializer = VerifyPaymentSerializer(data=request.data, context={'request': request})
		serializer.is_valid(raise_exception=True)
		payment = serializer.save()

		return Response(PaymentSerializer(payment).data, status=status.HTTP_200_OK)


class PaymentStatusAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request, payment_id):
		payment = Payment.objects.filter(pk=payment_id).first()
		if payment is None:
			return Response({'detail': 'Payment not found.'}, status=status.HTTP_404_NOT_FOUND)

		if payment.student_id != request.user.id and not _is_admin(request.user):
			return Response({'detail': 'You do not have permission to view this payment.'}, status=status.HTTP_403_FORBIDDEN)

		return Response(PaymentSerializer(payment).data, status=status.HTTP_200_OK)


class MyPaymentsAPIView(generics.ListAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = PaymentSerializer

	def get_queryset(self):
		return Payment.objects.filter(student=self.request.user).select_related('course').order_by('-created_at')


# =========================================================
# Streak
# =========================================================

class MyStreakAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		streak, _ = LearningStreak.objects.get_or_create(student=request.user)
		return Response(LearningStreakSerializer(streak).data, status=status.HTTP_200_OK)


class StreakLeaderboardAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		limit = int(request.query_params.get('limit', 20))
		top_streaks = LearningStreak.objects.select_related('student').filter(
			current_streak__gt=0
		).order_by('-current_streak', '-longest_streak')[:limit]

		data = [
			{
				'rank': index + 1,
				'student_id': streak.student_id,
				'student_name': streak.student.name,
				'current_streak': streak.current_streak,
				'longest_streak': streak.longest_streak,
			}
			for index, streak in enumerate(top_streaks)
		]

		return Response(LeaderboardEntrySerializer(data, many=True).data, status=status.HTTP_200_OK)


# =========================================================
# Certificate
# =========================================================

class CheckCourseCertificateAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request, course_id):
		course = Course.objects.filter(pk=course_id, course_type='skill').first()
		if course is None:
			return Response({'detail': 'Skill course not found.'}, status=status.HTTP_404_NOT_FOUND)

		student = request.user

		existing = Certificate.objects.filter(student=student, course=course).first()
		if existing is not None:
			return Response(CertificateSerializer(existing).data, status=status.HTTP_200_OK)

		if not _check_course_certificate_eligibility(student, course):
			return Response({'detail': 'You have not yet met the criteria for this certificate.'}, status=status.HTTP_400_BAD_REQUEST)

		certificate = Certificate.objects.create(student=student, certificate_type='course', course=course)
		return Response(CertificateSerializer(certificate).data, status=status.HTTP_201_CREATED)


class CheckGradeCertificateAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		student = request.user
		student_grade = getattr(getattr(student, 'student_profile', None), 'grade', None)

		if student_grade is None:
			return Response({'detail': 'You do not have a grade set on your profile.'}, status=status.HTTP_400_BAD_REQUEST)

		existing = Certificate.objects.filter(student=student, grade=student_grade).first()
		if existing is not None:
			return Response(CertificateSerializer(existing).data, status=status.HTTP_200_OK)

		if not _check_grade_certificate_eligibility(student, student_grade):
			return Response({'detail': 'You have not yet met the criteria for this certificate.'}, status=status.HTTP_400_BAD_REQUEST)

		certificate = Certificate.objects.create(student=student, certificate_type='grade', grade=student_grade)
		return Response(CertificateSerializer(certificate).data, status=status.HTTP_201_CREATED)


class MyCertificatesAPIView(generics.ListAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = CertificateSerializer

	def get_queryset(self):
		return Certificate.objects.filter(student=self.request.user).select_related('course', 'grade').order_by('-issued_at')


# =========================================================
# Badges
# =========================================================

class BadgeListCreateAPIView(generics.ListCreateAPIView):
	serializer_class = BadgeSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		queryset = Badge.objects.all()

		if not _is_admin(self.request.user):
			queryset = queryset.filter(
				is_active=True
			)

		return queryset.order_by('name')

	def perform_create(self, serializer):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can create badges.'
			)

		serializer.save()


class BadgeDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	serializer_class = BadgeSerializer
	authentication_classes = [
		JWTAuthentication,
		SessionAuthentication,
	]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		queryset = Badge.objects.all()

		if not _is_admin(self.request.user):
			queryset = queryset.filter(
				is_active=True
			)

		return queryset

	def perform_update(self, serializer):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can update badges.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		if not _is_admin(self.request.user):
			raise PermissionDenied(
				'Only administrators can delete badges.'
			)

		instance.delete()


class MyBadgesAPIView(generics.ListAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = StudentBadgeSerializer

	def get_queryset(self):
		return StudentBadge.objects.filter(
			student=self.request.user
		).select_related('badge').order_by('-awarded_at')


# =========================================================
# Complete Student Profile
# =========================================================

class CompleteStudentProfileAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		user = request.user

		if not _is_student(user):
			return Response(
				{'detail': 'Only students can complete this profile step.'},
				status=status.HTTP_403_FORBIDDEN,
			)

		serializer = CompleteStudentProfileSerializer(
			data=request.data,
			context={'request': request},
		)
		serializer.is_valid(raise_exception=True)
		profile = serializer.save()

		return Response(
			{
				'detail': 'Profile completed successfully.',
				'onboarding_completed': True,
				'grade': profile.grade_id,
				'province': profile.province_id,
				'district': profile.district_id,
				'municipality': profile.municipality_id,
				'school': profile.school_id,
			},
			status=status.HTTP_200_OK,
		)


# =========================================================
# Challenges
# =========================================================

def _my_challenge_statuses(user):
	return dict(
		ChallengeParticipant.objects.filter(
			student=user
		).values_list('challenge_id', 'status')
	)


def _can_manage_challenge(user, challenge):
	return (
		_is_admin(user)
		or challenge.created_by_id == user.id
	)


class ChallengeAccessMixin:
	def get_challenge_queryset(self):
		user = self.request.user

		queryset = Challenge.objects.select_related(
			'subject',
			'grade',
			'created_by',
		).annotate(
			participant_count=Count('participants', distinct=True)
		).prefetch_related(
			Prefetch(
				'participants',
				queryset=ChallengeParticipant.objects.filter(
					is_winner=True
				).select_related('student'),
				to_attr='winner_participants',
			)
		)

		if _is_admin(user):
			return queryset

		if _is_instructor(user):
			return queryset.filter(
				Q(is_published=True)
				| Q(created_by=user)
			)

		return queryset.filter(
			is_published=True
		)

	def get_serializer_context(self):
		context = super().get_serializer_context()
		context['my_statuses'] = _my_challenge_statuses(self.request.user)
		return context


class ChallengeListCreateAPIView(
	ChallengeAccessMixin,
	generics.ListCreateAPIView
):
	serializer_class = ChallengeSerializer
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		queryset = self.get_challenge_queryset()
		params = self.request.query_params

		subject_id = params.get('subject')
		grade_id = params.get('grade')
		ended = params.get('ended')

		if subject_id:
			queryset = queryset.filter(
				subject_id=subject_id
			)

		if grade_id:
			queryset = queryset.filter(
				grade_id=grade_id
			)

		if ended is not None:
			now = timezone.now()

			if ended.lower() == 'true':
				queryset = queryset.filter(
					end_at__lte=now
				)

			elif ended.lower() == 'false':
				queryset = queryset.filter(
					end_at__gt=now
				)

		return queryset.order_by('-created_at')

	def perform_create(self, serializer):
		user = self.request.user

		if not (
			_is_instructor(user)
			or _is_admin(user)
		):
			raise PermissionDenied(
				'Only instructors or administrators can create challenges.'
			)

		serializer.save(
			created_by=user,
			is_published=False,
		)


class ChallengeDetailAPIView(
	ChallengeAccessMixin,
	generics.RetrieveUpdateDestroyAPIView
):
	serializer_class = ChallengeSerializer
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get_queryset(self):
		return self.get_challenge_queryset()

	def perform_update(self, serializer):
		challenge = serializer.instance
		user = self.request.user

		if not _can_manage_challenge(user, challenge):
			raise PermissionDenied(
				'Only the challenge creator or an administrator '
				'can modify this challenge.'
			)

		requested_publish = serializer.validated_data.get(
			'is_published',
			challenge.is_published,
		)

		if (
			requested_publish
			and not challenge.is_published
			and not _is_admin(user)
			and not _is_verified_instructor(user)
		):
			raise PermissionDenied(
				'Only verified instructors can publish challenges.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		if not _can_manage_challenge(self.request.user, instance):
			raise PermissionDenied(
				'Only the challenge creator or an administrator '
				'can delete this challenge.'
			)

		if instance.participants.exists():
			raise ValidationError({
				'detail': (
					'This challenge has participants and cannot be deleted. '
					'Unpublish it instead.'
				)
			})

		instance.delete()


class JoinChallengeAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request, challenge_id):
		user = request.user

		if not _is_student(user):
			return Response(
				{'detail': 'Only students can join challenges.'},
				status=status.HTTP_403_FORBIDDEN,
			)

		challenge = Challenge.objects.filter(
			pk=challenge_id,
			is_published=True,
		).first()

		if challenge is None:
			return Response(
				{'detail': 'Challenge not found.'},
				status=status.HTTP_404_NOT_FOUND,
			)

		if challenge.end_at <= timezone.now():
			return Response(
				{'detail': 'This challenge has ended.'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		participant, created = ChallengeParticipant.objects.get_or_create(
			challenge=challenge,
			student=user,
		)

		return Response(
			ChallengeParticipantSerializer(participant).data,
			status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
		)


class SubmitChallengeAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request, challenge_id):
		user = request.user

		if not _is_student(user):
			return Response(
				{'detail': 'Only students can submit challenge work.'},
				status=status.HTTP_403_FORBIDDEN,
			)

		participant = ChallengeParticipant.objects.select_related(
			'challenge'
		).filter(
			challenge_id=challenge_id,
			student=user,
		).first()

		if participant is None:
			return Response(
				{'detail': 'You have not joined this challenge.'},
				status=status.HTTP_404_NOT_FOUND,
			)

		challenge = participant.challenge

		if not challenge.is_published:
			return Response(
				{'detail': 'This challenge is not available.'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		if challenge.end_at <= timezone.now():
			return Response(
				{'detail': 'This challenge has ended.'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		if participant.status == 'approved':
			return Response(
				{'detail': 'Your submission has already been approved.'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		serializer = ChallengeSubmitSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		updated = ChallengeParticipant.objects.filter(
			pk=participant.pk,
		).exclude(
			status='approved',
		).update(
			submission_text=serializer.validated_data['submission_text'],
			submission_url=serializer.validated_data['submission_url'],
			status='submitted',
			submitted_at=timezone.now(),
			reviewed_by=None,
			reviewed_at=None,
		)

		if not updated:
			return Response(
				{'detail': 'Your submission has already been approved.'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		participant = ChallengeParticipant.objects.select_related(
			'challenge',
			'student',
			'reviewed_by',
		).get(pk=participant.pk)

		return Response(
			ChallengeParticipantSerializer(participant).data,
			status=status.HTTP_200_OK,
		)


class ChallengeParticipantListAPIView(generics.ListAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = ChallengeParticipantSerializer

	def get_queryset(self):
		challenge = Challenge.objects.filter(
			pk=self.kwargs['challenge_id']
		).first()

		if challenge is None:
			raise NotFound(
				'Challenge not found.'
			)

		if not _can_manage_challenge(self.request.user, challenge):
			raise PermissionDenied(
				'Only the challenge creator or an administrator '
				'can view its participants.'
			)

		queryset = challenge.participants.select_related(
			'challenge',
			'student',
			'reviewed_by',
		)

		status_filter = self.request.query_params.get('status')

		if status_filter:
			queryset = queryset.filter(
				status=status_filter
			)

		return queryset.order_by('-joined_at')


class ReviewChallengeSubmissionAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	@transaction.atomic
	def post(self, request, participant_id):
		user = request.user

		participant = ChallengeParticipant.objects.select_related(
			'challenge',
			'student',
		).filter(
			pk=participant_id,
		).first()

		if participant is None:
			return Response(
				{'detail': 'Participant not found.'},
				status=status.HTTP_404_NOT_FOUND,
			)

		challenge = participant.challenge

		if not _can_manage_challenge(user, challenge):
			raise PermissionDenied(
				'Only the challenge creator or an administrator '
				'can review submissions.'
			)

		serializer = ChallengeReviewSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		action = serializer.validated_data['action']

		if participant.status != 'submitted':
			return Response(
				{'detail': 'Only submitted work can be reviewed.'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		if action == 'approve':
			points = challenge.points

			updated = ChallengeParticipant.objects.filter(
				pk=participant.pk,
				status='submitted',
			).update(
				status='approved',
				reviewed_by=user,
				reviewed_at=timezone.now(),
				points_awarded=points,
			)

			if not updated:
				return Response(
					{'detail': 'This submission has already been reviewed.'},
					status=status.HTTP_400_BAD_REQUEST,
				)

			if points > 0:
				PointTransaction.objects.create(
					student=participant.student,
					points=points,
					event_type='challenge_completion',
					description=f'Challenge completed: {challenge.title}',
				)

		else:
			updated = ChallengeParticipant.objects.filter(
				pk=participant.pk,
				status='submitted',
			).update(
				status='rejected',
				reviewed_by=user,
				reviewed_at=timezone.now(),
				points_awarded=0,
			)

			if not updated:
				return Response(
					{'detail': 'This submission has already been reviewed.'},
					status=status.HTTP_400_BAD_REQUEST,
				)

		participant = ChallengeParticipant.objects.select_related(
			'challenge',
			'student',
			'reviewed_by',
		).get(pk=participant.pk)

		return Response(
			ChallengeParticipantSerializer(participant).data,
			status=status.HTTP_200_OK,
		)


class SetChallengeWinnersAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	@transaction.atomic
	def post(self, request, challenge_id):
		challenge = Challenge.objects.filter(pk=challenge_id).first()

		if challenge is None:
			return Response(
				{'detail': 'Challenge not found.'},
				status=status.HTTP_404_NOT_FOUND,
			)

		if not _can_manage_challenge(request.user, challenge):
			raise PermissionDenied(
				'Only the challenge creator or an administrator '
				'can set winners.'
			)

		if challenge.end_at > timezone.now():
			return Response(
				{'detail': 'Winners can only be set after the challenge has ended.'},
				status=status.HTTP_400_BAD_REQUEST,
			)

		serializer = ChallengeWinnersSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		requested_ids = set(serializer.validated_data['participants'])

		valid_ids = set(
			ChallengeParticipant.objects.filter(
				challenge=challenge,
				status='approved',
				pk__in=requested_ids,
			).values_list('pk', flat=True)
		)

		invalid_ids = sorted(requested_ids - valid_ids)

		if invalid_ids:
			return Response(
				{
					'detail': 'Winners must be approved participants of this challenge.',
					'invalid_participants': invalid_ids,
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		challenge.participants.update(is_winner=False)

		if valid_ids:
			challenge.participants.filter(
				pk__in=valid_ids
			).update(is_winner=True)

		winners = challenge.participants.filter(
			is_winner=True
		).select_related(
			'challenge',
			'student',
			'reviewed_by',
		)

		return Response(
			ChallengeParticipantSerializer(winners, many=True).data,
			status=status.HTTP_200_OK,
		)


class MyChallengesAPIView(generics.ListAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = ChallengeParticipantSerializer

	def get_queryset(self):
		return ChallengeParticipant.objects.filter(
			student=self.request.user
		).select_related(
			'challenge',
			'student',
			'reviewed_by',
		).order_by('-joined_at')


# =========================================================
# Quiz Management
# =========================================================

class QuizListCreateAPIView(generics.ListCreateAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = QuizManagementSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = Quiz.objects.select_related(
			'course',
			'course__instructor'
		).prefetch_related(
			'questions__options'
		)

		if _is_admin(user):
			return queryset.order_by('-created_at')

		if _is_instructor(user):
			return queryset.filter(
				course__instructor=user
			).order_by('-created_at')

		return queryset.none()

	def perform_create(self, serializer):
		course = serializer.validated_data['course']
		user = self.request.user

		if not (
			_is_instructor(user)
			or _is_admin(user)
		):
			raise PermissionDenied(
				'Only instructors can create quizzes.'
			)

		if (
			not _is_admin(user)
			and course.instructor_id != user.id
		):
			raise PermissionDenied(
				'You can only create quizzes '
				'for your own courses.'
			)

		serializer.save(is_published=False)


class QuizDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = QuizManagementSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = Quiz.objects.select_related(
			'course',
			'course__instructor'
		).prefetch_related(
			'questions__options'
		)

		if _is_admin(user):
			return queryset

		if _is_instructor(user):
			return queryset.filter(
				course__instructor=user
			)

		return queryset.none()

	def perform_update(self, serializer):
		quiz = self.get_object()
		user = self.request.user

		if not (
			_is_admin(user)
			or quiz.course.instructor_id == user.id
		):
			raise PermissionDenied(
				'You can only update quizzes '
				'for your own courses.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		user = self.request.user

		if not (
			_is_admin(user)
			or instance.course.instructor_id == user.id
		):
			raise PermissionDenied(
				'You can only delete quizzes '
				'from your own courses.'
			)

		instance.delete()


# =========================================================
# Question Management
# =========================================================

class QuestionListCreateAPIView(
	generics.ListCreateAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = QuestionManagementSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = Question.objects.select_related(
			'quiz',
			'quiz__course',
			'quiz__course__instructor'
		).prefetch_related(
			'options'
		)

		if _is_admin(user):
			return queryset

		if _is_instructor(user):
			return queryset.filter(
				quiz__course__instructor=user
			)

		return queryset.none()

	def perform_create(self, serializer):
		quiz = serializer.validated_data['quiz']
		user = self.request.user

		if not (
			_is_instructor(user)
			or _is_admin(user)
		):
			raise PermissionDenied(
				'Only instructors can create questions.'
			)

		if (
			not _is_admin(user)
			and quiz.course.instructor_id != user.id
		):
			raise PermissionDenied(
				'You can only add questions to quizzes '
				'from your own courses.'
			)

		serializer.save()


class QuestionDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = QuestionManagementSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = Question.objects.select_related(
			'quiz',
			'quiz__course',
			'quiz__course__instructor'
		).prefetch_related(
			'options'
		)

		if _is_admin(user):
			return queryset

		if _is_instructor(user):
			return queryset.filter(
				quiz__course__instructor=user
			)

		return queryset.none()

	def perform_update(self, serializer):
		question = self.get_object()
		user = self.request.user

		if (
			not _is_admin(user)
			and question.quiz.course.instructor_id != user.id
		):
			raise PermissionDenied(
				'You can only update questions '
				'from your own quizzes.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		user = self.request.user

		if (
			not _is_admin(user)
			and instance.quiz.course.instructor_id != user.id
		):
			raise PermissionDenied(
				'You can only delete questions '
				'from your own quizzes.'
			)

		instance.delete()


# =========================================================
# Question Option Management
# =========================================================

class QuestionOptionListCreateAPIView(
	generics.ListCreateAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = QuestionOptionManagementSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = QuestionOption.objects.select_related(
			'question',
			'question__quiz',
			'question__quiz__course',
			'question__quiz__course__instructor'
		)

		if _is_admin(user):
			return queryset

		if _is_instructor(user):
			return queryset.filter(
				question__quiz__course__instructor=user
			)

		return queryset.none()

	def perform_create(self, serializer):
		question = serializer.validated_data['question']
		user = self.request.user

		if not (
			_is_instructor(user)
			or _is_admin(user)
		):
			raise PermissionDenied(
				'Only instructors can create question options.'
			)

		if (
			not _is_admin(user)
			and question.quiz.course.instructor_id != user.id
		):
			raise PermissionDenied(
				'You can only add options to questions '
				'from your own quizzes.'
			)

		serializer.save()


class QuestionOptionDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = QuestionOptionManagementSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = QuestionOption.objects.select_related(
			'question',
			'question__quiz',
			'question__quiz__course',
			'question__quiz__course__instructor'
		)

		if _is_admin(user):
			return queryset

		if _is_instructor(user):
			return queryset.filter(
				question__quiz__course__instructor=user
			)

		return queryset.none()

	def perform_update(self, serializer):
		option = self.get_object()
		user = self.request.user

		if (
			not _is_admin(user)
			and option.question.quiz.course.instructor_id != user.id
		):
			raise PermissionDenied(
				'You can only update options '
				'from your own quizzes.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		user = self.request.user

		if (
			not _is_admin(user)
			and instance.question.quiz.course.instructor_id != user.id
		):
			raise PermissionDenied(
				'You can only delete options '
				'from your own quizzes.'
			)

		instance.delete()


# =========================================================
# Student Quiz Access
# =========================================================

class StudentQuizDetailAPIView(
	generics.RetrieveAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = QuizStudentSerializer

	def get_queryset(self):
		return Quiz.objects.filter(
			is_published=True,
			course__is_published=True
		).select_related(
			'course'
		).prefetch_related(
			'questions__options'
		)

	def get_object(self):
		quiz = super().get_object()
		user = self.request.user

		enrollment = Enrollment.objects.filter(
			student=user,
			course=quiz.course,
			status__in=['active', 'completed']
		).first()

		if not enrollment:
			raise PermissionDenied(
				'You must be enrolled in this course '
				'to access this quiz.'
			)

		return quiz


# =========================================================
# Start Quiz Attempt
# =========================================================

class StartQuizAttemptAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request, quiz_id):
		student = request.user

		quiz = Quiz.objects.filter(
			id=quiz_id,
			is_published=True,
			course__is_published=True
		).select_related(
			'course'
		).first()

		if quiz is None:
			return Response(
				{'detail': 'Quiz not found or not published.'},
				status=status.HTTP_404_NOT_FOUND,
			)

		enrollment = Enrollment.objects.filter(
			student=student,
			course=quiz.course,
			status__in=['active', 'completed']
		).first()

		if enrollment is None:
			return Response(
				{
					'detail': (
						'You must be enrolled in this course '
						'before attempting this quiz.'
					)
				},
				status=status.HTTP_403_FORBIDDEN,
			)

		completed_attempts = QuizAttempt.objects.filter(
			student=student,
			quiz=quiz,
			completed_at__isnull=False
		).count()

		if completed_attempts >= quiz.max_attempts:
			return Response(
				{
					'detail': (
						'Maximum quiz attempts reached.'
					),
					'max_attempts': quiz.max_attempts,
					'attempts_used': completed_attempts,
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		existing_attempt = QuizAttempt.objects.filter(
			student=student,
			quiz=quiz,
			completed_at__isnull=True
		).first()

		if existing_attempt:
			return Response(
				QuizAttemptSerializer(
					existing_attempt
				).data,
				status=status.HTTP_200_OK,
			)

		attempt = QuizAttempt.objects.create(
			student=student,
			quiz=quiz,
			enrollment=enrollment,
		)

		return Response(
			QuizAttemptSerializer(attempt).data,
			status=status.HTTP_201_CREATED,
		)


class SubmitQuizAttemptAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	@transaction.atomic
	def post(self, request, attempt_id):
		student = request.user

		attempt = QuizAttempt.objects.select_related(
			'quiz',
			'enrollment',
			'quiz__course'
		).filter(
			id=attempt_id,
			student=student
		).first()

		if attempt is None:
			return Response(
				{'detail': 'Quiz attempt not found.'},
				status=status.HTTP_404_NOT_FOUND,
			)

		if attempt.completed_at is not None:
			return Response(
				{
					'detail':
						'This quiz attempt has already been submitted.'
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		serializer = QuizSubmitSerializer(
			data=request.data
		)
		serializer.is_valid(raise_exception=True)

		submitted_answers = serializer.validated_data['answers']

		questions = list(
			attempt.quiz.questions.prefetch_related(
				'options'
			).all()
		)

		if not questions:
			return Response(
				{
					'detail':
						'This quiz has no questions.'
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		quiz_question_ids = {
			question.id
			for question in questions
		}

		submitted_question_ids = {
			answer['question']
			for answer in submitted_answers
		}

		if submitted_question_ids != quiz_question_ids:
			return Response(
				{
					'detail': (
						'You must answer every question '
						'before submitting the quiz.'
					)
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		total_marks = sum(
			question.marks
			for question in questions
		)

		if total_marks <= 0:
			return Response(
				{
					'detail':
						'Quiz total marks must be greater than zero.'
				},
				status=status.HTTP_400_BAD_REQUEST,
			)

		question_map = {
			question.id: question
			for question in questions
		}

		score = Decimal('0.00')

		answers_to_create = []

		# -----------------------------------------
		# Points earned in this submission
		# -----------------------------------------
		points_earned = 0

		# Keep questions that should award points.
		point_awards = []

		for submitted_answer in submitted_answers:
			question_id = submitted_answer['question']
			option_id = submitted_answer['selected_option']

			question = question_map.get(question_id)

			if question is None:
				return Response(
					{
						'detail': (
							f'Question {question_id} does not '
							'belong to this quiz.'
						)
					},
					status=status.HTTP_400_BAD_REQUEST,
				)

			selected_option = next(
				(
					option
					for option in question.options.all()
					if option.id == option_id
				),
				None
			)

			if selected_option is None:
				return Response(
					{
						'detail': (
							f'Option {option_id} does not belong '
							f'to question {question_id}.'
						)
					},
					status=status.HTTP_400_BAD_REQUEST,
				)

			is_correct = selected_option.is_correct

			marks_awarded = (
				Decimal(str(question.marks))
				if is_correct
				else Decimal('0.00')
			)

			score += marks_awarded

			answers_to_create.append(
				StudentAnswer(
					attempt=attempt,
					question=question,
					selected_option=selected_option,
					is_correct=is_correct,
					marks_awarded=marks_awarded,
				)
			)

			# -----------------------------------------
			# Gamification points
			# -----------------------------------------
			if is_correct and question.points > 0:

				already_awarded = (
					PointTransaction.objects.filter(
						student=student,
						question=question,
						event_type='quiz_correct_answer'
					).exists()
				)

				if not already_awarded:
					points_earned += question.points
					point_awards.append(question)

		percentage = (
			score / Decimal(str(total_marks))
		) * Decimal('100')

		percentage = percentage.quantize(
			Decimal('0.01')
		)

		is_passed = (
			percentage >=
			Decimal(
				str(attempt.quiz.pass_percentage)
			)
		)

		# -----------------------------------------
		# Save answers
		# -----------------------------------------
		StudentAnswer.objects.bulk_create(
			answers_to_create
		)

		# -----------------------------------------
		# Complete quiz attempt
		# -----------------------------------------
		attempt.score = score
		attempt.percentage = percentage
		attempt.is_passed = is_passed
		attempt.completed_at = timezone.now()

		attempt.save(
			update_fields=[
				'score',
				'percentage',
				'is_passed',
				'completed_at',
			]
		)

		# -----------------------------------------
		# Create point transactions
		# -----------------------------------------
		point_transactions = []

		for question in point_awards:
			point_transactions.append(
				PointTransaction(
					student=student,
					points=question.points,
					event_type='quiz_correct_answer',
					quiz_attempt=attempt,
					question=question,
					description=(
						f'Correct answer in quiz: '
						f'{attempt.quiz.title}'
					),
				)
			)

		if point_transactions:
			PointTransaction.objects.bulk_create(
				point_transactions
			)

		_check_and_award_badges(student)

		# -----------------------------------------
		# Response
		# -----------------------------------------
		return Response(
			{
				'detail':
					'Quiz submitted successfully.',

				'attempt':
					QuizAttemptSerializer(
						attempt
					).data,

				'points_earned':
					points_earned,
			},
			status=status.HTTP_200_OK,
		)


# =========================================================
# Student Quiz Attempt History
# =========================================================

class StudentQuizAttemptHistoryAPIView(
	generics.ListAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = QuizAttemptSerializer

	def get_queryset(self):
		return QuizAttempt.objects.filter(
			student=self.request.user,
			completed_at__isnull=False
		).select_related(
			'quiz',
			'enrollment'
		).order_by(
			'-completed_at'
		)


# =========================================================
# Instructor Quiz Results
# =========================================================

class InstructorQuizResultsAPIView(
	generics.ListAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = InstructorQuizResultSerializer

	def get_queryset(self):
		user = self.request.user
		quiz_id = self.kwargs['quiz_id']

		quiz = Quiz.objects.select_related(
			'course',
			'course__instructor'
		).filter(
			id=quiz_id
		).first()

		if quiz is None:
			raise NotFound(
				'Quiz not found.'
			)

		if not _is_admin(user):
			if not _is_instructor(user):
				raise PermissionDenied(
					'Only instructors or admins can view quiz results.'
				)

			if quiz.course.instructor_id != user.id:
				raise PermissionDenied(
					'You can only view results for your own course.'
				)

		return QuizAttempt.objects.filter(
			quiz=quiz,
			completed_at__isnull=False
		).select_related(
			'student',
			'quiz',
			'enrollment'
		).order_by(
			'-completed_at'
		)


# =========================================================
# Points Leaderboard
# =========================================================


class PointsLeaderboardAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		try:
			limit = int(
				request.query_params.get(
					'limit',
					20
				)
			)
		except (TypeError, ValueError):
			limit = 20

		limit = max(1, min(limit, 100))

		students = (
			User.objects
			.filter(
				role__name='student',
				point_transactions__isnull=False
			)
			.annotate(
				total_points=Sum(
					'point_transactions__points'
				)
			)
			.order_by(
				'-total_points',
				'id'
			)[:limit]
		)

		data = [
			{
				'rank': index + 1,
				'student_id': student.id,
				'student_name': student.name,
				'total_points': student.total_points or 0,
			}
			for index, student in enumerate(
				students
			)
		]

		serializer = PointsLeaderboardEntrySerializer(
			data,
			many=True
		)

		return Response(
			serializer.data,
			status=status.HTTP_200_OK
		)


# =========================================================
# Student Points
# =========================================================


class StudentPointsAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		user = request.user

		if _role_name(user) != 'student':
			return Response(
				{
					'detail':
						'Only students can access points.'
				},
				status=status.HTTP_403_FORBIDDEN
			)

		transactions = (
			PointTransaction.objects
			.filter(student=user)
			.select_related(
				'quiz_attempt',
				'question'
			)
			.order_by('-created_at')
		)

		total_points = (
			transactions.aggregate(
				total=Sum('points')
			)['total']
			or 0
		)

		return Response(
			{
				'student_id': user.id,
				'student_name': user.name,
				'total_points': total_points,
				'transactions':
					PointTransactionSerializer(
						transactions,
						many=True
					).data,
			},
			status=status.HTTP_200_OK
		)


# =========================================================
# Shorts
# =========================================================

class ShortListCreateAPIView(generics.ListCreateAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = ShortSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = Short.objects.select_related(
			'instructor'
		).prefetch_related(
			'likes',
			'comments'
		)

		if _is_admin(user):
			return queryset.order_by('-created_at')

		if _is_instructor(user):
			return queryset.filter(
				Q(is_published=True) |
				Q(instructor=user)
			).order_by('-created_at')

		return queryset.filter(
			is_published=True
		).order_by('-created_at')

	def perform_create(self, serializer):
		user = self.request.user

		if not _is_verified_instructor(user):
			raise PermissionDenied(
				'Only verified instructors can create Shorts.'
			)

		serializer.save(
			instructor=user,
			is_published=False
		)


class ShortDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = ShortSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = Short.objects.select_related(
			'instructor'
		).prefetch_related(
			'likes',
			'comments'
		)

		if _is_admin(user):
			return queryset

		if _is_instructor(user):
			return queryset.filter(
				Q(is_published=True) |
				Q(instructor=user)
			)

		return queryset.filter(
			is_published=True
		)

	def _check_owner_or_admin(self, short):
		user = self.request.user

		if not (
			_is_admin(user)
			or short.instructor_id == user.id
		):
			raise PermissionDenied(
				'Only the Short owner or administrator '
				'can modify this Short.'
			)

	def perform_update(self, serializer):
		short = self.get_object()
		user = self.request.user

		self._check_owner_or_admin(short)

		requested_publish = serializer.validated_data.get(
			'is_published',
			short.is_published
		)

		if (
			requested_publish
			and not short.is_published
			and not _is_admin(user)
			and not _is_verified_instructor(user)
		):
			raise PermissionDenied(
				'Only verified instructors can publish Shorts.'
			)

		serializer.save()

	def perform_destroy(self, instance):
		self._check_owner_or_admin(instance)
		instance.delete()


# =========================================================
# Student Short View
# =========================================================

class RecordShortViewAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	@transaction.atomic
	def post(self, request, short_id):
		user = request.user

		if _role_name(user) != 'student':
			return Response(
				{
					'detail':
						'Only students can record Short views.'
				},
				status=status.HTTP_403_FORBIDDEN
			)

		short = Short.objects.select_for_update().filter(
			id=short_id,
			is_published=True
		).first()

		if short is None:
			return Response(
				{
					'detail':
						'Short not found or not published.'
				},
				status=status.HTTP_404_NOT_FOUND
			)

		short_view, created = ShortView.objects.get_or_create(
			student=user,
			short=short
		)

		if created:
			short.view_count += 1
			short.save(
				update_fields=['view_count']
			)

		return Response(
			{
				'detail': (
					'Short view recorded.'
					if created
					else 'Short was already viewed.'
				),
				'new_view': created,
				'view_count': short.view_count,
				'view': ShortViewSerializer(
					short_view
				).data,
			},
			status=(
				status.HTTP_201_CREATED
				if created
				else status.HTTP_200_OK
			)
		)


# =========================================================
# Short Like / Unlike
# =========================================================

class ToggleShortLikeAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	@transaction.atomic
	def post(self, request, short_id):
		user = request.user

		if _role_name(user) != 'student':
			return Response(
				{
					'detail':
						'Only students can like Shorts.'
				},
				status=status.HTTP_403_FORBIDDEN
			)

		short = Short.objects.filter(
			id=short_id,
			is_published=True
		).first()

		if short is None:
			return Response(
				{
					'detail':
						'Short not found or not published.'
				},
				status=status.HTTP_404_NOT_FOUND
			)

		existing_like = ShortLike.objects.filter(
			student=user,
			short=short
		).first()

		if existing_like:
			existing_like.delete()

			return Response(
				{
					'detail': 'Short unliked successfully.',
					'is_liked': False,
					'like_count': short.likes.count(),
				},
				status=status.HTTP_200_OK
			)

		short_like = ShortLike.objects.create(
			student=user,
			short=short
		)

		return Response(
			{
				'detail': 'Short liked successfully.',
				'is_liked': True,
				'like_count': short.likes.count(),
				'like': ShortLikeSerializer(
					short_like
				).data,
			},
			status=status.HTTP_201_CREATED
		)


# =========================================================
# Short Comments
# =========================================================

class ShortCommentListCreateAPIView(
	generics.ListCreateAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = ShortCommentSerializer

	def get_queryset(self):
		short_id = self.kwargs['short_id']

		short = Short.objects.filter(
			id=short_id,
			is_published=True
		).first()

		if short is None:
			raise NotFound(
				'Short not found or not published.'
			)

		return ShortComment.objects.filter(
			short=short
		).select_related(
			'student',
			'short'
		).order_by(
			'-created_at'
		)

	def perform_create(self, serializer):
		user = self.request.user
		short_id = self.kwargs['short_id']

		if _role_name(user) != 'student':
			raise PermissionDenied(
				'Only students can comment on Shorts.'
			)

		short = Short.objects.filter(
			id=short_id,
			is_published=True
		).first()

		if short is None:
			raise NotFound(
				'Short not found or not published.'
			)

		text = serializer.validated_data.get(
			'text',
			''
		).strip()

		if not text:
			raise serializers.ValidationError({
				'text': 'Comment cannot be empty.'
			})

		serializer.save(
			student=user,
			short=short,
			text=text
		)


class ShortCommentDetailAPIView(
	generics.RetrieveDestroyAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = ShortCommentSerializer

	queryset = ShortComment.objects.select_related(
		'student',
		'short'
	)

	def perform_destroy(self, instance):
		user = self.request.user

		if not (
			_is_admin(user)
			or instance.student_id == user.id
			or instance.short.instructor_id == user.id
		):
			raise PermissionDenied(
				'You do not have permission '
				'to delete this comment.'
			)

		instance.delete()


# =========================================================
# eBooks
# =========================================================

class EBookListCreateAPIView(generics.ListCreateAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = EBookSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = EBook.objects.select_related(
			'subject',
			'grade',
			'uploaded_by',
		)

		if _is_admin(user):
			pass

		elif _is_instructor(user):
			queryset = queryset.filter(
				Q(is_published=True)
				| Q(uploaded_by=user)
			)

		else:
			queryset = queryset.filter(
				is_published=True
			)

		subject_id = self.request.query_params.get('subject')
		grade_id = self.request.query_params.get('grade')

		if subject_id:
			queryset = queryset.filter(
				subject_id=subject_id
			)

		if grade_id:
			queryset = queryset.filter(
				grade_id=grade_id
			)

		return queryset.order_by('-created_at')

	def perform_create(self, serializer):
		user = self.request.user

		if not (
			_is_admin(user)
			or _is_verified_instructor(user)
		):
			raise PermissionDenied(
				'Only verified instructors or administrators '
				'can upload eBooks.'
			)

		serializer.save(uploaded_by=user)


class EBookDetailAPIView(
	generics.RetrieveUpdateDestroyAPIView
):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = EBookSerializer

	def get_queryset(self):
		user = self.request.user

		queryset = EBook.objects.select_related(
			'subject',
			'grade',
			'uploaded_by',
		)

		if _is_admin(user):
			return queryset

		if _is_instructor(user):
			return queryset.filter(
				Q(is_published=True)
				| Q(uploaded_by=user)
			)

		return queryset.filter(
			is_published=True
		)

	def _check_owner_or_admin(self, ebook):
		user = self.request.user

		if not (
			_is_admin(user)
			or ebook.uploaded_by_id == user.id
		):
			raise PermissionDenied(
				'Only the eBook owner or administrator '
				'can modify this eBook.'
			)

	def perform_update(self, serializer):
		ebook = self.get_object()
		self._check_owner_or_admin(ebook)
		serializer.save()

	def perform_destroy(self, instance):
		self._check_owner_or_admin(instance)
		instance.delete()


# =========================================================
# Notifications
# =========================================================
# NOTE: placeholder implementation — Alisa's original notification
# code was not available to merge (see chat). Replace this block
# with her actual views if/when you can get them from her.

class NotificationListAPIView(generics.ListAPIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]
	serializer_class = NotificationSerializer

	def get_queryset(self):
		queryset = Notification.objects.filter(
			recipient=self.request.user
		)

		is_read = self.request.query_params.get('is_read')

		if is_read is not None:
			if is_read.lower() == 'true':
				queryset = queryset.filter(is_read=True)
			elif is_read.lower() == 'false':
				queryset = queryset.filter(is_read=False)

		return queryset.order_by('-created_at')


class NotificationUnreadCountAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		count = Notification.objects.filter(
			recipient=request.user,
			is_read=False,
		).count()

		return Response(
			{'unread_count': count},
			status=status.HTTP_200_OK,
		)


class NotificationMarkReadAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request, pk):
		notification = Notification.objects.filter(
			pk=pk,
			recipient=request.user,
		).first()

		if notification is None:
			return Response(
				{'detail': 'Notification not found.'},
				status=status.HTTP_404_NOT_FOUND,
			)

		if not notification.is_read:
			notification.is_read = True
			notification.read_at = timezone.now()
			notification.save(update_fields=['is_read', 'read_at'])

		return Response(
			NotificationSerializer(notification).data,
			status=status.HTTP_200_OK,
		)


class NotificationMarkAllReadAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		updated = Notification.objects.filter(
			recipient=request.user,
			is_read=False,
		).update(
			is_read=True,
			read_at=timezone.now(),
		)

		return Response(
			{'detail': f'{updated} notification(s) marked as read.'},
			status=status.HTTP_200_OK,
		)


# =========================================================
# AI Assistant
# =========================================================

class AIAskAPIView(APIView):
	"""
	FR-AI-01:
	Allow students to submit learning questions
	to the SkillSikka AI assistant.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		role_name = getattr(
			getattr(request.user, 'role', None),
			'name',
			None
		)

		if role_name != 'student':
			return Response(
				{
					'detail': (
						'Only students can use the AI assistant.'
					)
				},
				status=status.HTTP_403_FORBIDDEN
			)

		question = request.data.get(
			'question',
			''
		).strip()

		learning_context = request.data.get(
			'learning_context',
			''
		).strip()

		if not question:
			return Response(
				{
					'question': [
						'Question is required.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(question) > 2000:
			return Response(
				{
					'question': [
						'Question must not exceed 2000 characters.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(learning_context) > 5000:
			return Response(
				{
					'learning_context': [
						'Learning context must not exceed 5000 characters.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		try:
			answer = GeminiService.ask_student_question(
				question=question,
				learning_context=(
					learning_context
					if learning_context
					else None
				)
			)

		except ValueError as exc:
			return Response(
				{
					'detail': str(exc)
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		except Exception:
			return Response(
				{
					'detail': (
						'The AI assistant is temporarily unavailable. '
						'Please try again later.'
					)
				},
				status=status.HTTP_503_SERVICE_UNAVAILABLE
			)

		return Response(
			{
				'question': question,
				'answer': answer
			},
			status=status.HTTP_200_OK
		)


class AIAssistAPIView(APIView):
	"""
	FR-AI-02:
	Provide explanations, hints, and guided assistance
	to authenticated students.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		role_name = getattr(
			getattr(request.user, 'role', None),
			'name',
			None
		)

		if role_name != 'student':
			return Response(
				{
					'detail': (
						'Only students can use AI assistance.'
					)
				},
				status=status.HTTP_403_FORBIDDEN
			)

		question = str(
			request.data.get('question', '')
		).strip()

		assistance_mode = str(
			request.data.get('assistance_mode', '')
		).strip().lower()

		learning_context = str(
			request.data.get('learning_context', '')
		).strip()

		if not question:
			return Response(
				{
					'question': [
						'Question is required.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(question) > 2000:
			return Response(
				{
					'question': [
						'Question must not exceed 2000 characters.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if assistance_mode not in GeminiService.ASSISTANCE_MODES:
			return Response(
				{
					'assistance_mode': [
						(
							'Invalid assistance mode. '
							'Use explain, hint, or guide.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(learning_context) > 5000:
			return Response(
				{
					'learning_context': [
						(
							'Learning context must not exceed '
							'5000 characters.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		try:
			answer = GeminiService.get_guided_assistance(
				question=question,
				assistance_mode=assistance_mode,
				learning_context=(
					learning_context
					if learning_context
					else None
				)
			)

		except ValueError as exc:
			return Response(
				{
					'detail': str(exc)
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		except Exception:
			return Response(
				{
					'detail': (
						'The AI assistant is temporarily unavailable. '
						'Please try again later.'
					)
				},
				status=status.HTTP_503_SERVICE_UNAVAILABLE
			)

		return Response(
			{
				'question': question,
				'assistance_mode': assistance_mode,
				'learning_context': (
					learning_context
					if learning_context
					else None
				),
				'answer': answer,
			},
			status=status.HTTP_200_OK
		)


class AIActivityGenerateAPIView(APIView):
	"""
	FR-AI-03 / FR-AI-04:
	Generate an AI educational activity and save it
	for teacher/admin review.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		role_name = getattr(
			getattr(request.user, 'role', None),
			'name',
			None
		)

		if role_name != 'student':
			return Response(
				{
					'detail': (
						'Only students can generate '
						'AI learning activities.'
					)
				},
				status=status.HTTP_403_FORBIDDEN
			)

		activity_type = str(
			request.data.get('activity_type', '')
		).strip().lower()

		topic = str(
			request.data.get('topic', '')
		).strip()

		learning_context = str(
			request.data.get('learning_context', '')
		).strip()

		difficulty = str(
			request.data.get('difficulty', 'medium')
		).strip().lower()

		question_count = request.data.get(
			'question_count',
			5
		)

		if activity_type not in GeminiService.ACTIVITY_TYPES:
			return Response(
				{
					'activity_type': [
						(
							'Invalid activity type. Use '
							'practice_questions, crossword, '
							'or challenge.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if not topic:
			return Response(
				{
					'topic': [
						'Topic is required.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(topic) > 255:
			return Response(
				{
					'topic': [
						'Topic must not exceed 255 characters.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(learning_context) > 5000:
			return Response(
				{
					'learning_context': [
						(
							'Learning context must not exceed '
							'5000 characters.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if difficulty not in {
			'easy',
			'medium',
			'hard',
		}:
			return Response(
				{
					'difficulty': [
						(
							'Difficulty must be easy, '
							'medium, or hard.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		try:
			question_count = int(question_count)
		except (TypeError, ValueError):
			return Response(
				{
					'question_count': [
						'Question count must be a number.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if question_count < 1 or question_count > 10:
			return Response(
				{
					'question_count': [
						(
							'Question count must be '
							'between 1 and 10.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		try:
			generated_content = (
				GeminiService.generate_educational_activity(
					activity_type=activity_type,
					topic=topic,
					learning_context=(
						learning_context
						if learning_context
						else None
					),
					difficulty=difficulty,
					question_count=question_count,
				)
			)

		except ValueError as exc:
			return Response(
				{
					'detail': str(exc)
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		except Exception:
			return Response(
				{
					'detail': (
						'The AI activity generator is '
						'temporarily unavailable. '
						'Please try again later.'
					)
				},
				status=status.HTTP_503_SERVICE_UNAVAILABLE
			)

		ai_activity = AIActivity.objects.create(
			generated_by=request.user,
			activity_type=activity_type,
			topic=topic,
			learning_context=learning_context,
			difficulty=difficulty,
			generated_content=generated_content,
			status='pending_review',
		)

		return Response(
			{
				'id': ai_activity.id,
				'activity_type': ai_activity.activity_type,
				'topic': ai_activity.topic,
				'difficulty': ai_activity.difficulty,
				'status': ai_activity.status,
				'activity': ai_activity.generated_content,
				'created_at': ai_activity.created_at,
			},
			status=status.HTTP_201_CREATED
		)


def _serialize_ai_activity(activity):
	"""
	Convert an AIActivity database object into API response data.
	"""

	return {
		'id': activity.id,
		'activity_type': activity.activity_type,
		'topic': activity.topic,
		'learning_context': activity.learning_context,
		'difficulty': activity.difficulty,
		'generated_content': activity.generated_content,
		'status': activity.status,
		'generated_by': {
			'id': activity.generated_by_id,
			'name': activity.generated_by.name,
			'email': activity.generated_by.email,
		},
		'reviewed_by': (
			{
				'id': activity.reviewed_by_id,
				'name': activity.reviewed_by.name,
				'email': activity.reviewed_by.email,
			}
			if activity.reviewed_by
			else None
		),
		'review_notes': activity.review_notes,
		'reviewed_at': activity.reviewed_at,
		'created_at': activity.created_at,
		'updated_at': activity.updated_at,
	}


def _can_review_ai_activity(user):
	"""
	AI-generated educational content may be reviewed by
	verified instructors, school admins, or super admins.
	"""

	role_name = _role_name(user)

	return (
		_is_admin(user)
		or _is_verified_instructor(user)
		or role_name == 'school_admin'
	)


class AIActivityPendingReviewAPIView(APIView):
	"""
	FR-AI-04:
	List AI-generated activities waiting for review.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		if not _can_review_ai_activity(request.user):
			return Response(
				{
					'detail': (
						'Only authorized teachers or '
						'administrators can review '
						'AI-generated activities.'
					)
				},
				status=status.HTTP_403_FORBIDDEN
			)

		activities = AIActivity.objects.filter(
			status='pending_review'
		).select_related(
			'generated_by',
			'reviewed_by',
		).order_by(
			'-created_at'
		)

		return Response(
			[
				_serialize_ai_activity(activity)
				for activity in activities
			],
			status=status.HTTP_200_OK
		)


class AIActivityDetailAPIView(APIView):
	"""
	FR-AI-04:
	View a generated AI activity.

	Students may view their own generated activity.
	Reviewers may view any activity requiring review.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request, activity_id):
		activity = AIActivity.objects.select_related(
			'generated_by',
			'reviewed_by',
		).filter(
			pk=activity_id
		).first()

		if activity is None:
			return Response(
				{
					'detail': 'AI activity not found.'
				},
				status=status.HTTP_404_NOT_FOUND
			)

		is_owner = (
			activity.generated_by_id
			== request.user.id
		)

		if not (
			is_owner
			or _can_review_ai_activity(request.user)
		):
			return Response(
				{
					'detail': (
						'You do not have permission '
						'to view this AI activity.'
					)
				},
				status=status.HTTP_403_FORBIDDEN
			)

		return Response(
			_serialize_ai_activity(activity),
			status=status.HTTP_200_OK
		)


class AIActivityReviewAPIView(APIView):
	"""
	FR-AI-04:
	Approve or reject AI-generated educational content.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	@transaction.atomic
	def post(self, request, activity_id):
		if not _can_review_ai_activity(request.user):
			return Response(
				{
					'detail': (
						'Only authorized teachers or '
						'administrators can review '
						'AI-generated activities.'
					)
				},
				status=status.HTTP_403_FORBIDDEN
			)

		activity = AIActivity.objects.select_for_update().filter(
			pk=activity_id
		).first()

		if activity is None:
			return Response(
				{
					'detail': 'AI activity not found.'
				},
				status=status.HTTP_404_NOT_FOUND
			)

		if activity.status != 'pending_review':
			return Response(
				{
					'detail': (
						'This AI activity has already '
						'been reviewed.'
					)
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		action = str(
			request.data.get('action', '')
		).strip().lower()

		review_notes = str(
			request.data.get('review_notes', '')
		).strip()

		if action not in {
			'approve',
			'reject',
		}:
			return Response(
				{
					'action': [
						'Action must be approve or reject.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(review_notes) > 2000:
			return Response(
				{
					'review_notes': [
						(
							'Review notes must not exceed '
							'2000 characters.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if action == 'reject' and not review_notes:
			return Response(
				{
					'review_notes': [
						(
							'Review notes are required '
							'when rejecting AI content.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		activity.status = (
			'approved'
			if action == 'approve'
			else 'rejected'
		)

		activity.reviewed_by = request.user
		activity.review_notes = review_notes
		activity.reviewed_at = timezone.now()

		activity.save(
			update_fields=[
				'status',
				'reviewed_by',
				'review_notes',
				'reviewed_at',
				'updated_at',
			]
		)

		activity = AIActivity.objects.select_related(
			'generated_by',
			'reviewed_by',
		).get(
			pk=activity.pk
		)

		return Response(
			_serialize_ai_activity(activity),
			status=status.HTTP_200_OK
		)


# =========================================================
# FR-AI-05 - AI Learning Recommendations
# =========================================================

class AIRecommendationAPIView(APIView):
	"""
	FR-AI-05:
	Recommend relevant SkillSikka courses, lessons,
	and educational videos to students.

	Gemini may only select content that currently exists
	in the SkillSikka database.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		if not _is_student(request.user):
			return Response(
				{
					'detail': (
						'Only students can request '
						'AI learning recommendations.'
					)
				},
				status=status.HTTP_403_FORBIDDEN
			)

		learning_goal = str(
			request.data.get('learning_goal', '')
		).strip()

		learning_context = str(
			request.data.get('learning_context', '')
		).strip()

		if not learning_goal:
			return Response(
				{
					'learning_goal': [
						'Learning goal is required.'
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(learning_goal) > 1000:
			return Response(
				{
					'learning_goal': [
						(
							'Learning goal must not exceed '
							'1000 characters.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(learning_context) > 5000:
			return Response(
				{
					'learning_context': [
						(
							'Learning context must not exceed '
							'5000 characters.'
						)
					]
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		# Only published courses are eligible for recommendation.
		courses = list(
			Course.objects.filter(
				is_published=True
			).select_related(
				'subject',
				'grade',
				'instructor',
			).order_by(
				'-created_at'
			)[:100]
		)

		course_ids = [
			course.id
			for course in courses
		]

		# Only lessons belonging to published courses are exposed
		# to the AI recommendation engine.
		lessons = list(
			Lesson.objects.filter(
				course_id__in=course_ids
			).select_related(
				'course',
				'topic',
			).order_by(
				'course_id',
				'order',
				'id',
			)[:200]
		)

		# Only published Shorts/videos are eligible.
		videos = list(
			Short.objects.filter(
				is_published=True
			).select_related(
				'instructor'
			).order_by(
				'-created_at'
			)[:100]
		)

		try:
			recommendations = (
				GeminiService.recommend_learning_content(
					learning_goal=learning_goal,
					learning_context=(
						learning_context
						if learning_context
						else None
					),
					courses=courses,
					lessons=lessons,
					videos=videos,
				)
			)

		except ValueError as exc:
			return Response(
				{
					'detail': str(exc)
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		except Exception:
			return Response(
				{
					'detail': (
						'The AI recommendation service is '
						'temporarily unavailable. '
						'Please try again later.'
					)
				},
				status=status.HTTP_503_SERVICE_UNAVAILABLE
			)

		course_map = {
			course.id: course
			for course in courses
		}

		lesson_map = {
			lesson.id: lesson
			for lesson in lessons
		}

		video_map = {
			video.id: video
			for video in videos
		}

		recommended_courses = []

		for item in recommendations.get('courses', []):
			course = course_map.get(
				item.get('id')
			)

			if course is None:
				continue

			recommended_courses.append({
				'id': course.id,
				'title': course.title,
				'description': course.description,
				'course_type': course.course_type,
				'subject': (
					str(course.subject)
					if course.subject
					else None
				),
				'grade': (
					str(course.grade)
					if course.grade
					else None
				),
				'is_paid': course.is_paid,
				'price': str(course.price),
				'thumbnail_url': course.thumbnail_url,
				'reason': item.get('reason', ''),
			})

		recommended_lessons = []

		for item in recommendations.get('lessons', []):
			lesson = lesson_map.get(
				item.get('id')
			)

			if lesson is None:
				continue

			recommended_lessons.append({
				'id': lesson.id,
				'title': lesson.title,
				'topic': (
					str(lesson.topic)
					if lesson.topic
					else None
				),
				'content_type': lesson.content_type,
				'course': {
					'id': lesson.course_id,
					'title': (
						lesson.course.title
						if lesson.course
						else None
					),
				},
				'reason': item.get('reason', ''),
			})

		recommended_videos = []

		for item in recommendations.get('videos', []):
			video = video_map.get(
				item.get('id')
			)

			if video is None:
				continue

			recommended_videos.append({
				'id': video.id,
				'title': video.title,
				'video_url': video.video_url,
				'thumbnail_url': video.thumbnail_url,
				'view_count': video.view_count,
				'reason': item.get('reason', ''),
			})

		return Response(
			{
				'learning_goal': learning_goal,
				'learning_context': (
					learning_context
					if learning_context
					else None
				),
				'recommendations': {
					'courses': recommended_courses,
					'lessons': recommended_lessons,
					'videos': recommended_videos,
				},
			},
			status=status.HTTP_200_OK
		)


# =========================================================
# Municipality Dashboard
# =========================================================

class MunicipalityDashboardAPIView(APIView):
	"""
	Municipality / Local-Level analytics dashboard.

	Implements the currently supported parts of:
	FR-LOC-01 to FR-LOC-09.

	Current database limitations:
	- Ward statistics are not available because StudentProfile
	  does not currently contain a ward field.
	- Challenge statistics are not included here because the
	  current core models do not contain challenge models.
	- Educational expenditure statistics are not available
	  because there is no expenditure model.

	Until a documented municipality-to-user scope mapping exists,
	only Super Admin can select a municipality for this endpoint.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		user = request.user
		role_name = _role_name(user)

		# -------------------------------------------------
		# Access control / Geographic scope
		# FR-LOC-12
		# -------------------------------------------------

		# Super Admin can inspect any municipality.
		if _is_admin(user):
			municipality_id = request.query_params.get(
				'municipality_id'
			)

			if not municipality_id:
				return Response(
					{
						'detail': (
							'municipality_id query parameter '
							'is required for Super Admin.'
						)
					},
					status=status.HTTP_400_BAD_REQUEST
				)

			municipality = (
				Municipality.objects
				.select_related(
					'district',
					'district__province'
				)
				.filter(id=municipality_id)
				.first()
			)

			if municipality is None:
				return Response(
					{
						'detail': 'Municipality not found.'
					},
					status=status.HTTP_404_NOT_FOUND
				)

		# Local Authority is automatically restricted
		# to the municipality assigned to its profile.
		elif role_name == 'local_authority':
			try:
				authority_profile = (
					LocalAuthorityProfile.objects
					.select_related(
						'municipality',
						'municipality__district',
						'municipality__district__province'
					)
					.get(user=user)
				)

			except LocalAuthorityProfile.DoesNotExist:
				return Response(
					{
						'detail': (
							'No municipality scope is assigned '
							'to this Local Authority account.'
						)
					},
					status=status.HTTP_403_FORBIDDEN
				)

			municipality = authority_profile.municipality

			requested_municipality_id = (
				request.query_params.get(
					'municipality_id'
				)
			)

			# Local Authority may omit municipality_id completely.
			# Its assigned municipality will automatically be used.
			#
			# If municipality_id is supplied, it MUST match
			# the assigned municipality.
			if requested_municipality_id:
				try:
					requested_municipality_id = int(
						requested_municipality_id
					)

				except (TypeError, ValueError):
					return Response(
						{
							'detail': (
								'municipality_id must be '
								'a valid integer.'
							)
						},
						status=status.HTTP_400_BAD_REQUEST
					)

				if (
					requested_municipality_id
					!= municipality.id
				):
					return Response(
						{
							'detail': (
								'You are not authorized to access '
								'data for this municipality.'
							)
						},
						status=status.HTTP_403_FORBIDDEN
					)

		# Other roles cannot access Municipality dashboard.
		else:
			return Response(
				{
					'detail': (
						'You are not authorized to access '
						'the Municipality dashboard.'
					)
				},
				status=status.HTTP_403_FORBIDDEN
			)

		# -------------------------------------------------
		# Students inside selected municipality
		# -------------------------------------------------
		students = (
			User.objects
			.filter(
				role__name='student',
				student_profile__municipality=municipality
			)
			.select_related(
				'student_profile',
				'student_profile__grade',
				'student_profile__school'
			)
		)

		student_ids = students.values_list(
			'id',
			flat=True
		)

		total_students = students.count()

		# -------------------------------------------------
		# Schools
		# -------------------------------------------------
		schools = School.objects.filter(
			municipality=municipality
		)

		total_schools = schools.count()

		school_statistics = list(
			students
			.values(
				'student_profile__school_id',
				'student_profile__school__name'
			)
			.annotate(
				total_students=Count('id')
			)
			.order_by(
				'-total_students',
				'student_profile__school__name'
			)
		)

		school_statistics = [
			{
				'school_id':
					row['student_profile__school_id'],
				'school_name':
					row['student_profile__school__name']
					or 'Not specified',
				'total_students':
					row['total_students'],
			}
			for row in school_statistics
		]

		# -------------------------------------------------
		# Grade-wise student statistics
		# FR-LOC-03
		# -------------------------------------------------
		grade_statistics = list(
			students
			.values(
				'student_profile__grade_id',
				'student_profile__grade__name'
			)
			.annotate(
				total_students=Count('id')
			)
			.order_by(
				'student_profile__grade__name'
			)
		)

		grade_statistics = [
			{
				'grade_id':
					row['student_profile__grade_id'],
				'grade_name':
					row['student_profile__grade__name']
					or 'Not specified',
				'total_students':
					row['total_students'],
			}
			for row in grade_statistics
		]

		# -------------------------------------------------
		# Gender distribution
		# FR-LOC-04
		# -------------------------------------------------
		gender_rows = list(
			students
			.values('gender')
			.annotate(
				total_students=Count('id')
			)
			.order_by('gender')
		)

		gender_statistics = [
			{
				'gender':
					row['gender']
					if row['gender']
					else 'not_specified',
				'total_students':
					row['total_students'],
			}
			for row in gender_rows
		]

		# -------------------------------------------------
		# Enrollment / Course Participation
		# FR-LOC-07
		# -------------------------------------------------
		enrollments = Enrollment.objects.filter(
			student_id__in=student_ids
		)

		total_enrollments = enrollments.count()

		active_enrollments = enrollments.filter(
			status='active'
		).count()

		completed_enrollments = enrollments.filter(
			status='completed'
		).count()

		cancelled_enrollments = enrollments.filter(
			status='cancelled'
		).count()

		pending_payment_enrollments = enrollments.filter(
			status='pending_payment'
		).count()

		completion_rate = (
			round(
				(
					completed_enrollments
					/ total_enrollments
				) * 100,
				2
			)
			if total_enrollments > 0
			else 0.0
		)

		# -------------------------------------------------
		# Popular / Highly Engaged Courses
		# FR-LOC-09
		# -------------------------------------------------
		popular_course_rows = (
			enrollments
			.values(
				'course_id',
				'course__title',
				'course__subject_id',
				'course__subject__name'
			)
			.annotate(
				total_participants=Count(
					'student_id',
					distinct=True
				),
				completed_students=Count(
					'student_id',
					filter=Q(status='completed'),
					distinct=True
				)
			)
			.order_by(
				'-total_participants',
				'course__title'
			)[:10]
		)

		popular_courses = [
			{
				'course_id':
					row['course_id'],
				'course_title':
					row['course__title'],
				'subject_id':
					row['course__subject_id'],
				'subject_name':
					row['course__subject__name'],
				'total_participants':
					row['total_participants'],
				'completed_students':
					row['completed_students'],
			}
			for row in popular_course_rows
		]

		# -------------------------------------------------
		# Popular Subjects
		# FR-LOC-09
		# -------------------------------------------------
		popular_subject_rows = (
			enrollments
			.filter(
				course__subject__isnull=False
			)
			.values(
				'course__subject_id',
				'course__subject__name'
			)
			.annotate(
				total_participations=Count('id'),
				unique_students=Count(
					'student_id',
					distinct=True
				)
			)
			.order_by(
				'-total_participations',
				'course__subject__name'
			)[:10]
		)

		popular_subjects = [
			{
				'subject_id':
					row['course__subject_id'],
				'subject_name':
					row['course__subject__name'],
				'total_participations':
					row['total_participations'],
				'unique_students':
					row['unique_students'],
			}
			for row in popular_subject_rows
		]

		# -------------------------------------------------
		# Assessment statistics
		# FR-LOC-05
		# -------------------------------------------------
		answers = StudentAnswer.objects.filter(
			attempt__student_id__in=student_ids,
			attempt__completed_at__isnull=False
		)

		total_answers = answers.count()

		correct_answers = answers.filter(
			is_correct=True
		).count()

		incorrect_answers = answers.filter(
			is_correct=False
		).count()

		correct_percentage = (
			round(
				(
					correct_answers
					/ total_answers
				) * 100,
				2
			)
			if total_answers > 0
			else 0.0
		)

		incorrect_percentage = (
			round(
				(
					incorrect_answers
					/ total_answers
				) * 100,
				2
			)
			if total_answers > 0
			else 0.0
		)

		# -------------------------------------------------
		# First-time-correct statistics
		# FR-LOC-06
		#
		# A first-time-correct answer means the question was
		# answered correctly on the student's earliest
		# completed attempt for that quiz.
		# -------------------------------------------------
		completed_attempts = (
			QuizAttempt.objects
			.filter(
				student_id__in=student_ids,
				completed_at__isnull=False
			)
			.order_by(
				'student_id',
				'quiz_id',
				'started_at',
				'id'
			)
		)

		first_attempt_ids = []
		seen_student_quizzes = set()

		for attempt in completed_attempts:
			key = (
				attempt.student_id,
				attempt.quiz_id
			)

			if key not in seen_student_quizzes:
				seen_student_quizzes.add(key)
				first_attempt_ids.append(
					attempt.id
				)

		first_attempt_answers = (
			StudentAnswer.objects
			.filter(
				attempt_id__in=first_attempt_ids
			)
		)

		first_attempt_total_answers = (
			first_attempt_answers.count()
		)

		first_time_correct_answers = (
			first_attempt_answers
			.filter(is_correct=True)
			.count()
		)

		first_time_correct_percentage = (
			round(
				(
					first_time_correct_answers
					/ first_attempt_total_answers
				) * 100,
				2
			)
			if first_attempt_total_answers > 0
			else 0.0
		)

		# -------------------------------------------------
		# Quiz / Assessment performance
		# -------------------------------------------------
		quiz_attempts = (
			QuizAttempt.objects
			.filter(
				student_id__in=student_ids,
				completed_at__isnull=False
			)
		)

		total_quiz_attempts = quiz_attempts.count()

		passed_quiz_attempts = quiz_attempts.filter(
			is_passed=True
		).count()

		failed_quiz_attempts = quiz_attempts.filter(
			is_passed=False
		).count()

		average_quiz_percentage = (
			quiz_attempts.aggregate(
				average=Avg('percentage')
			)['average']
		)

		if average_quiz_percentage is None:
			average_quiz_percentage = 0.0
		else:
			average_quiz_percentage = round(
				float(average_quiz_percentage),
				2
			)

		quiz_pass_rate = (
			round(
				(
					passed_quiz_attempts
					/ total_quiz_attempts
				) * 100,
				2
			)
			if total_quiz_attempts > 0
			else 0.0
		)

		# -------------------------------------------------
		# Grade-wise performance
		# FR-LOC-08
		# -------------------------------------------------
		grade_performance_rows = (
			quiz_attempts
			.filter(
				student__student_profile__grade__isnull=False
			)
			.values(
				'student__student_profile__grade_id',
				'student__student_profile__grade__name'
			)
			.annotate(
				total_attempts=Count('id'),
				average_percentage=Avg('percentage'),
				passed_attempts=Count(
					'id',
					filter=Q(is_passed=True)
				)
			)
			.order_by(
				'student__student_profile__grade__name'
			)
		)

		grade_performance = []

		for row in grade_performance_rows:
			attempts = row['total_attempts']
			passed = row['passed_attempts']

			grade_performance.append(
				{
					'grade_id':
						row[
							'student__student_profile__grade_id'
						],
					'grade_name':
						row[
							'student__student_profile__grade__name'
						],
					'total_attempts':
						attempts,
					'average_percentage':
						round(
							float(
								row['average_percentage']
								or 0
							),
							2
						),
					'passed_attempts':
						passed,
					'pass_rate':
						round(
							(
								passed / attempts
							) * 100,
							2
						)
						if attempts > 0
						else 0.0,
				}
			)

		# -------------------------------------------------
		# Subject-wise performance
		# FR-LOC-08
		# -------------------------------------------------
		subject_performance_rows = (
			quiz_attempts
			.filter(
				quiz__course__subject__isnull=False
			)
			.values(
				'quiz__course__subject_id',
				'quiz__course__subject__name'
			)
			.annotate(
				total_attempts=Count('id'),
				average_percentage=Avg('percentage'),
				passed_attempts=Count(
					'id',
					filter=Q(is_passed=True)
				)
			)
			.order_by(
				'quiz__course__subject__name'
			)
		)

		subject_performance = []

		for row in subject_performance_rows:
			attempts = row['total_attempts']
			passed = row['passed_attempts']

			subject_performance.append(
				{
					'subject_id':
						row[
							'quiz__course__subject_id'
						],
					'subject_name':
						row[
							'quiz__course__subject__name'
						],
					'total_attempts':
						attempts,
					'average_percentage':
						round(
							float(
								row['average_percentage']
								or 0
							),
							2
						),
					'passed_attempts':
						passed,
					'pass_rate':
						round(
							(
								passed / attempts
							) * 100,
							2
						)
						if attempts > 0
						else 0.0,
				}
			)

		# -------------------------------------------------
		# Response
		# -------------------------------------------------
		return Response(
			{
				'municipality': {
					'id': municipality.id,
					'name': municipality.name,
					'district': municipality.district.name,
					'province':
						municipality.district.province.name,
				},

				'overview': {
					'total_students': total_students,
					'total_schools': total_schools,
					'total_enrollments': total_enrollments,
					'active_enrollments': active_enrollments,
					'completed_enrollments':
						completed_enrollments,
					'completion_rate':
						completion_rate,
				},

				'student_statistics': {
					'by_grade': grade_statistics,
					'by_school': school_statistics,
					'by_gender': gender_statistics,

					'by_ward': {
						'available': False,
						'reason': (
							'Ward information is not currently '
							'stored in StudentProfile.'
						),
					},
				},

				'course_statistics': {
					'total_participations':
						total_enrollments,
					'active':
						active_enrollments,
					'completed':
						completed_enrollments,
					'cancelled':
						cancelled_enrollments,
					'pending_payment':
						pending_payment_enrollments,
					'completion_rate':
						completion_rate,
					'popular_courses':
						popular_courses,
					'popular_subjects':
						popular_subjects,
				},

				'assessment_statistics': {
					'total_answers':
						total_answers,
					'correct_answers':
						correct_answers,
					'incorrect_answers':
						incorrect_answers,
					'correct_percentage':
						correct_percentage,
					'incorrect_percentage':
						incorrect_percentage,

					'first_attempt_answers':
						first_attempt_total_answers,
					'first_time_correct_answers':
						first_time_correct_answers,
					'first_time_correct_percentage':
						first_time_correct_percentage,

					'total_quiz_attempts':
						total_quiz_attempts,
					'passed_quiz_attempts':
						passed_quiz_attempts,
					'failed_quiz_attempts':
						failed_quiz_attempts,
					'average_quiz_percentage':
						average_quiz_percentage,
					'quiz_pass_rate':
						quiz_pass_rate,
				},

				'performance_statistics': {
					'by_grade':
						grade_performance,
					'by_subject':
						subject_performance,
				},

				'challenge_statistics': {
					'available': False,
					'reason': (
						'Challenge models are not currently '
						'available in the supplied core models.'
					),
				},

				'educational_program_expenditure_statistics': {
					'available': False,
					'reason': (
						'No educational expenditure model is '
						'currently available.'
					),
				},
			},
			status=status.HTTP_200_OK
		)


# =========================================================
# Ministry Dashboard
# =========================================================

class MinistryDashboardAPIView(APIView):
	"""
	National-level aggregated educational dashboard.

	Provides Ministry/Super Admin with aggregated statistics across:
	- Provinces
	- Districts
	- Municipalities
	- Students
	- Schools
	- Course participation
	- Assessment performance
	- Grade-wise performance
	- Subject-wise performance
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		user = request.user
		role_name = getattr(getattr(user, 'role', None), 'name', '')

		# Until dedicated Ministry accounts are configured,
		# Super Admin can access this dashboard for testing/admin purposes.
		if not (user.is_superuser or role_name in ['super_admin', 'ministry']):
			return Response(
				{
					'detail': 'You do not have permission to access the Ministry dashboard.'
				},
				status=status.HTTP_403_FORBIDDEN
			)

		# -------------------------------------------------
		# Base querysets
		# -------------------------------------------------

		students = User.objects.filter(
			role__name='student'
		).select_related(
			'student_profile__province',
			'student_profile__district',
			'student_profile__municipality',
			'student_profile__school',
			'student_profile__grade',
		)

		enrollments = Enrollment.objects.filter(
			student__role__name='student'
		)

		quiz_attempts = QuizAttempt.objects.filter(
			student__role__name='student'
		)

		student_answers = StudentAnswer.objects.filter(
			attempt__student__role__name='student'
		)

		# -------------------------------------------------
		# National overview
		# -------------------------------------------------

		total_students = students.count()
		total_schools = School.objects.count()
		total_enrollments = enrollments.count()

		active_enrollments = enrollments.filter(
			status='active'
		).count()

		completed_enrollments = enrollments.filter(
			status='completed'
		).count()

		completion_rate = (
			round(
				(completed_enrollments / total_enrollments) * 100,
				2
			)
			if total_enrollments
			else 0.0
		)

		# -------------------------------------------------
		# Province-wise student statistics
		# -------------------------------------------------

		province_statistics = []

		provinces = Province.objects.all().order_by('name')

		for province in provinces:
			province_students = students.filter(
				student_profile__province=province
			)

			province_enrollments = enrollments.filter(
				student__student_profile__province=province
			)

			province_attempts = quiz_attempts.filter(
				student__student_profile__province=province
			)

			province_attempt_count = province_attempts.count()

			province_average = province_attempts.aggregate(
				average=Avg('percentage')
			)['average']

			province_passed = province_attempts.filter(
				is_passed=True
			).count()

			province_statistics.append({
				'province_id': province.id,
				'province_name': province.name,
				'total_students': province_students.count(),
				'total_schools': School.objects.filter(
					municipality__district__province=province
				).count(),
				'total_enrollments': province_enrollments.count(),
				'total_quiz_attempts': province_attempt_count,
				'average_quiz_percentage': round(
					float(province_average or 0),
					2
				),
				'quiz_pass_rate': (
					round(
						(province_passed / province_attempt_count) * 100,
						2
					)
					if province_attempt_count
					else 0.0
				),
			})

		# -------------------------------------------------
		# District-wise student statistics
		# -------------------------------------------------

		district_statistics = list(
			students.values(
				'student_profile__district_id',
				'student_profile__district__name',
				'student_profile__district__province__name',
			)
			.annotate(total_students=Count('id'))
			.order_by(
				'student_profile__district__province__name',
				'student_profile__district__name'
			)
		)

		district_statistics = [
			{
				'district_id':
					item['student_profile__district_id'],

				'district_name':
					item['student_profile__district__name']
					or 'Not specified',

				'province_name':
					item[
						'student_profile__district__province__name'
					] or 'Not specified',

				'total_students':
					item['total_students'],
			}
			for item in district_statistics
		]

		# -------------------------------------------------
		# Municipality-wise statistics
		# -------------------------------------------------

		municipality_statistics = list(
			students.values(
				'student_profile__municipality_id',
				'student_profile__municipality__name',
				'student_profile__municipality__district__name',
				'student_profile__municipality__district__province__name',
			)
			.annotate(total_students=Count('id'))
			.order_by('-total_students')
		)

		municipality_statistics = [
			{
				'municipality_id':
					item['student_profile__municipality_id'],

				'municipality_name':
					item['student_profile__municipality__name']
					or 'Not specified',

				'district_name':
					item[
						'student_profile__municipality__district__name'
					] or 'Not specified',

				'province_name':
					item[
						'student_profile__municipality__district__province__name'
					] or 'Not specified',

				'total_students':
					item['total_students'],
			}
			for item in municipality_statistics
		]

		# -------------------------------------------------
		# Grade distribution
		# -------------------------------------------------

		grade_statistics = list(
			students.values(
				'student_profile__grade_id',
				'student_profile__grade__name',
			)
			.annotate(total_students=Count('id'))
			.order_by('student_profile__grade__name')
		)

		grade_statistics = [
			{
				'grade_id':
					item['student_profile__grade_id'],

				'grade_name':
					item['student_profile__grade__name']
					or 'Not specified',

				'total_students':
					item['total_students'],
			}
			for item in grade_statistics
		]

		# -------------------------------------------------
		# Gender distribution
		# -------------------------------------------------

		gender_statistics = list(
			students.values('gender')
			.annotate(total_students=Count('id'))
			.order_by('gender')
		)

		gender_statistics = [
			{
				'gender':
					item['gender'] or 'Not specified',

				'total_students':
					item['total_students'],
			}
			for item in gender_statistics
		]

		# -------------------------------------------------
		# Course participation
		# -------------------------------------------------

		cancelled_enrollments = enrollments.filter(
			status='cancelled'
		).count()

		pending_payment_enrollments = enrollments.filter(
			status='pending_payment'
		).count()

		popular_courses = list(
			enrollments.values(
				'course_id',
				'course__title',
				'course__subject_id',
				'course__subject__name',
			)
			.annotate(
				total_participants=Count('student', distinct=True),
				completed_students=Count(
					'student',
					filter=Q(status='completed'),
					distinct=True,
				),
			)
			.order_by('-total_participants')[:10]
		)

		popular_courses = [
			{
				'course_id': item['course_id'],
				'course_title': item['course__title'],
				'subject_id': item['course__subject_id'],
				'subject_name': item['course__subject__name'],
				'total_participants': item['total_participants'],
				'completed_students': item['completed_students'],
			}
			for item in popular_courses
		]

		popular_subjects = list(
			enrollments.exclude(
				course__subject__isnull=True
			)
			.values(
				'course__subject_id',
				'course__subject__name',
			)
			.annotate(
				total_participants=Count(
					'student',
					distinct=True
				)
			)
			.order_by('-total_participants')[:10]
		)

		popular_subjects = [
			{
				'subject_id': item['course__subject_id'],
				'subject_name': item['course__subject__name'],
				'total_participants': item['total_participants'],
			}
			for item in popular_subjects
		]

		# -------------------------------------------------
		# Assessment statistics
		# -------------------------------------------------

		total_answers = student_answers.count()

		correct_answers = student_answers.filter(
			is_correct=True
		).count()

		incorrect_answers = total_answers - correct_answers

		correct_percentage = (
			round(
				(correct_answers / total_answers) * 100,
				2
			)
			if total_answers
			else 0.0
		)

		incorrect_percentage = (
			round(
				(incorrect_answers / total_answers) * 100,
				2
			)
			if total_answers
			else 0.0
		)

		total_quiz_attempts = quiz_attempts.count()

		passed_quiz_attempts = quiz_attempts.filter(
			is_passed=True
		).count()

		failed_quiz_attempts = (
			total_quiz_attempts - passed_quiz_attempts
		)

		average_quiz_percentage = quiz_attempts.aggregate(
			average=Avg('percentage')
		)['average']

		quiz_pass_rate = (
			round(
				(
					passed_quiz_attempts
					/ total_quiz_attempts
				) * 100,
				2
			)
			if total_quiz_attempts
			else 0.0
		)

		# -------------------------------------------------
		# First-time-correct statistics
		# -------------------------------------------------

		completed_attempts = quiz_attempts.filter(
			completed_at__isnull=False
		).order_by(
			'student_id',
			'quiz_id',
			'started_at',
			'id'
		)

		first_attempt_ids = []
		seen_student_quizzes = set()

		for attempt in completed_attempts:
			key = (
				attempt.student_id,
				attempt.quiz_id,
			)

			if key not in seen_student_quizzes:
				seen_student_quizzes.add(key)
				first_attempt_ids.append(attempt.id)

		first_attempt_answers = student_answers.filter(
			attempt_id__in=first_attempt_ids
		)

		first_attempt_answer_count = (
			first_attempt_answers.count()
		)

		first_time_correct_answers = (
			first_attempt_answers.filter(
				is_correct=True
			).count()
		)

		first_time_correct_percentage = (
			round(
				(
					first_time_correct_answers
					/ first_attempt_answer_count
				) * 100,
				2
			)
			if first_attempt_answer_count
			else 0.0
		)

		# -------------------------------------------------
		# Grade-wise performance
		# -------------------------------------------------

		grade_performance = list(
			quiz_attempts.exclude(
				student__student_profile__grade__isnull=True
			)
			.values(
				'student__student_profile__grade_id',
				'student__student_profile__grade__name',
			)
			.annotate(
				total_attempts=Count('id'),
				average_percentage=Avg('percentage'),
				passed_attempts=Count(
					'id',
					filter=Q(is_passed=True)
				),
			)
			.order_by(
				'student__student_profile__grade__name'
			)
		)

		grade_performance_result = []

		for item in grade_performance:
			total = item['total_attempts']
			passed = item['passed_attempts']

			grade_performance_result.append({
				'grade_id':
					item[
						'student__student_profile__grade_id'
					],

				'grade_name':
					item[
						'student__student_profile__grade__name'
					],

				'total_attempts':
					total,

				'average_percentage':
					round(
						float(
							item['average_percentage'] or 0
						),
						2
					),

				'passed_attempts':
					passed,

				'pass_rate':
					(
						round(
							(passed / total) * 100,
							2
						)
						if total
						else 0.0
					),
			})

		# -------------------------------------------------
		# Subject-wise performance
		# -------------------------------------------------

		subject_performance = list(
			quiz_attempts.exclude(
				quiz__course__subject__isnull=True
			)
			.values(
				'quiz__course__subject_id',
				'quiz__course__subject__name',
			)
			.annotate(
				total_attempts=Count('id'),
				average_percentage=Avg('percentage'),
				passed_attempts=Count(
					'id',
					filter=Q(is_passed=True)
				),
			)
			.order_by('-total_attempts')
		)

		subject_performance_result = []

		for item in subject_performance:
			total = item['total_attempts']
			passed = item['passed_attempts']

			subject_performance_result.append({
				'subject_id':
					item['quiz__course__subject_id'],

				'subject_name':
					item['quiz__course__subject__name'],

				'total_attempts':
					total,

				'average_percentage':
					round(
						float(
							item['average_percentage'] or 0
						),
						2
					),

				'passed_attempts':
					passed,

				'pass_rate':
					(
						round(
							(passed / total) * 100,
							2
						)
						if total
						else 0.0
					),
			})

		# -------------------------------------------------
		# Response
		# -------------------------------------------------

		return Response(
			{
				'overview': {
					'total_provinces': Province.objects.count(),
					'total_districts': District.objects.count(),
					'total_municipalities':
						Municipality.objects.count(),
					'total_schools': total_schools,
					'total_students': total_students,
					'total_enrollments': total_enrollments,
					'active_enrollments': active_enrollments,
					'completed_enrollments':
						completed_enrollments,
					'completion_rate': completion_rate,
				},

				'geographical_statistics': {
					'by_province': province_statistics,
					'by_district': district_statistics,
					'by_municipality':
						municipality_statistics,
				},

				'student_statistics': {
					'by_grade': grade_statistics,
					'by_gender': gender_statistics,
				},

				'course_statistics': {
					'total_participations':
						total_enrollments,
					'active': active_enrollments,
					'completed': completed_enrollments,
					'cancelled': cancelled_enrollments,
					'pending_payment':
						pending_payment_enrollments,
					'completion_rate': completion_rate,
					'popular_courses': popular_courses,
					'popular_subjects': popular_subjects,
				},

				'assessment_statistics': {
					'total_answers': total_answers,
					'correct_answers': correct_answers,
					'incorrect_answers': incorrect_answers,
					'correct_percentage':
						correct_percentage,
					'incorrect_percentage':
						incorrect_percentage,

					'first_attempt_answers':
						first_attempt_answer_count,
					'first_time_correct_answers':
						first_time_correct_answers,
					'first_time_correct_percentage':
						first_time_correct_percentage,

					'total_quiz_attempts':
						total_quiz_attempts,
					'passed_quiz_attempts':
						passed_quiz_attempts,
					'failed_quiz_attempts':
						failed_quiz_attempts,
					'average_quiz_percentage':
						round(
							float(
								average_quiz_percentage or 0
							),
							2
						),
					'quiz_pass_rate':
						quiz_pass_rate,
				},

				'performance_statistics': {
					'by_grade':
						grade_performance_result,
					'by_subject':
						subject_performance_result,
				},

				# Challenge work is being developed separately.
				'challenge_statistics': {
					'available': False,
					'reason':
						'Challenge statistics will be integrated '
						'after the challenge feature is available.'
				},
			},
			status=status.HTTP_200_OK
		)


# =========================================================
# Super Admin - User Management
# =========================================================

def _get_client_ip(request):
	forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')

	if forwarded_for:
		return forwarded_for.split(',')[0].strip()

	return request.META.get('REMOTE_ADDR')


def _create_audit_log(
	request,
	action,
	target_type,
	target_id=None,
	target_display='',
	description='',
	metadata=None
):
	AuditLog.objects.create(
		actor=request.user,
		action=action,
		target_type=target_type,
		target_id=target_id,
		target_display=target_display,
		description=description,
		metadata=metadata or {},
		ip_address=_get_client_ip(request)
	)


class SuperAdminRequiredMixin:
	"""
	Restricts access to Super Admin users only.
	"""

	def check_super_admin(self, request):
		user = request.user

		if not (
			user.is_superuser
			or _role_name(user) == 'super_admin'
		):
			raise PermissionDenied(
				'Only Super Admin can perform this action.'
			)


class SuperAdminUserListAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	List and filter platform users.

	Query parameters:
	- role
	- verification_status
	- is_active
	- search
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		self.check_super_admin(request)

		users = User.objects.select_related(
			'role',
			'verified_by'
		).all().order_by('-created_at')

		role = request.query_params.get('role')
		verification_status = request.query_params.get(
			'verification_status'
		)
		is_active = request.query_params.get('is_active')
		search = request.query_params.get('search')

		if role:
			users = users.filter(role__name=role)

		if verification_status:
			users = users.filter(
				verification_status=verification_status
			)

		if is_active is not None:
			value = is_active.lower()

			if value in ['true', '1', 'yes']:
				users = users.filter(is_active=True)

			elif value in ['false', '0', 'no']:
				users = users.filter(is_active=False)

			else:
				return Response(
					{
						'detail':
							'is_active must be true or false.'
					},
					status=status.HTTP_400_BAD_REQUEST
				)

		if search:
			users = users.filter(
				Q(name__icontains=search)
				| Q(email__icontains=search)
				| Q(phone_number__icontains=search)
			)

		results = []

		for user in users:
			results.append({
				'id': user.id,
				'name': user.name,
				'email': user.email,
				'phone_country_code':
					user.phone_country_code,
				'phone_number': user.phone_number,
				'role': (
					user.role.name
					if user.role
					else None
				),
				'verification_status':
					user.verification_status,
				'is_active': user.is_active,
				'is_staff': user.is_staff,
				'is_superuser': user.is_superuser,
				'onboarding_completed':
					user.onboarding_completed,
				'verified_by': (
					{
						'id': user.verified_by.id,
						'name': user.verified_by.name,
						'email': user.verified_by.email,
					}
					if user.verified_by
					else None
				),
				'verified_at': user.verified_at,
				'created_at': user.created_at,
				'updated_at': user.updated_at,
			})

		return Response(
			{
				'count': len(results),
				'results': results,
			},
			status=status.HTTP_200_OK
		)


class SuperAdminUserDetailAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	Retrieve an individual user's administrative details.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request, user_id):
		self.check_super_admin(request)

		try:
			user = User.objects.select_related(
				'role',
				'verified_by'
			).get(pk=user_id)

		except User.DoesNotExist:
			raise NotFound('User not found.')

		data = {
			'id': user.id,
			'name': user.name,
			'email': user.email,
			'phone_country_code':
				user.phone_country_code,
			'phone_number': user.phone_number,
			'gender': user.gender,
			'dob': user.dob,
			'location': user.location,
			'profile_photo_url':
				user.profile_photo_url,
			'role': (
				user.role.name
				if user.role
				else None
			),
			'verification_status':
				user.verification_status,
			'is_active': user.is_active,
			'is_staff': user.is_staff,
			'is_superuser': user.is_superuser,
			'onboarding_completed':
				user.onboarding_completed,
			'onboarding_step':
				user.onboarding_step,
			'verified_by': (
				{
					'id': user.verified_by.id,
					'name': user.verified_by.name,
					'email': user.verified_by.email,
				}
				if user.verified_by
				else None
			),
			'verified_at': user.verified_at,
			'last_login': user.last_login,
			'created_at': user.created_at,
			'updated_at': user.updated_at,
		}

		return Response(
			data,
			status=status.HTTP_200_OK
		)


class SuperAdminUserStatusAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	Activate or deactivate a user account.

	Body:
	{
		"is_active": true
	}
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def patch(self, request, user_id):
		self.check_super_admin(request)

		try:
			target_user = User.objects.get(pk=user_id)

		except User.DoesNotExist:
			raise NotFound('User not found.')

		if target_user.id == request.user.id:
			return Response(
				{
					'detail':
						'You cannot change the active status '
						'of your own Super Admin account.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if 'is_active' not in request.data:
			return Response(
				{
					'detail':
						'is_active is required.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		is_active = request.data.get('is_active')

		if not isinstance(is_active, bool):
			return Response(
				{
					'detail':
						'is_active must be a boolean.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		previous_status = target_user.is_active

		target_user.is_active = is_active

		target_user.save(
			update_fields=[
				'is_active',
				'updated_at',
			]
		)

		_create_audit_log(
			request=request,
			action='activate' if is_active else 'deactivate',
			target_type='user',
			target_id=target_user.id,
			target_display=target_user.email,
			description=(
				f'User {target_user.email} was '
				f'{"activated" if is_active else "deactivated"}.'
			),
			metadata={
				'previous_is_active': previous_status,
				'new_is_active': is_active,
			}
		)

		return Response(
			{
				'detail': (
					'User activated successfully.'
					if is_active
					else 'User deactivated successfully.'
				),
				'user': {
					'id': target_user.id,
					'name': target_user.name,
					'email': target_user.email,
					'is_active': target_user.is_active,
				},
			},
			status=status.HTTP_200_OK
		)


class SuperAdminUserRoleAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	Change a user's assigned role.

	Body:
	{
		"role": "instructor"
	}
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def patch(self, request, user_id):
		self.check_super_admin(request)

		try:
			target_user = User.objects.select_related(
				'role'
			).get(pk=user_id)

		except User.DoesNotExist:
			raise NotFound('User not found.')

		if target_user.id == request.user.id:
			return Response(
				{
					'detail':
						'You cannot change your own '
						'Super Admin role.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		role_name = request.data.get('role')

		if not role_name:
			return Response(
				{
					'detail':
						'role is required.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		try:
			role = Role.objects.get(name=role_name)

		except Role.DoesNotExist:
			return Response(
				{
					'detail': 'Invalid role.',
					'available_roles': list(
						Role.objects.values_list(
							'name',
							flat=True
						)
					),
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		old_role = (
			target_user.role.name
			if target_user.role
			else None
		)

		target_user.role = role

		target_user.save(
			update_fields=[
				'role',
				'updated_at',
			]
		)

		_create_audit_log(
			request=request,
			action='role_change',
			target_type='user',
			target_id=target_user.id,
			target_display=target_user.email,
			description=(
				f'Role for {target_user.email} changed '
				f'from {old_role} to {role.name}.'
			),
			metadata={
				'previous_role': old_role,
				'new_role': role.name,
			}
		)

		return Response(
			{
				'detail':
					'User role updated successfully.',
				'user': {
					'id': target_user.id,
					'name': target_user.name,
					'email': target_user.email,
					'previous_role': old_role,
					'role': role.name,
				},
			},
			status=status.HTTP_200_OK
		)


class SuperAdminInstructorVerificationAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	Verify or reject an instructor account.

	Body:
	{
		"verification_status": "verified"
	}

	Supported values:
	- pending
	- verified
	- rejected
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def patch(self, request, user_id):
		self.check_super_admin(request)

		try:
			instructor = User.objects.select_related(
				'role'
			).get(pk=user_id)

		except User.DoesNotExist:
			raise NotFound('User not found.')

		if _role_name(instructor) != 'instructor':
			return Response(
				{
					'detail':
						'The selected user is not '
						'an instructor.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		verification_status = request.data.get(
			'verification_status'
		)

		allowed_statuses = [
			'pending',
			'verified',
			'rejected',
		]

		if verification_status not in allowed_statuses:
			return Response(
				{
					'detail':
						'verification_status must be '
						'pending, verified, or rejected.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		old_verification_status = (
			instructor.verification_status
		)

		instructor.verification_status = (
			verification_status
		)

		if verification_status == 'verified':
			instructor.verified_by = request.user
			instructor.verified_at = timezone.now()

		else:
			instructor.verified_by = None
			instructor.verified_at = None

		instructor.save(
			update_fields=[
				'verification_status',
				'verified_by',
				'verified_at',
				'updated_at',
			]
		)

		_create_audit_log(
			request=request,
			action='verification_change',
			target_type='instructor',
			target_id=instructor.id,
			target_display=instructor.email,
			description=(
				f'Instructor {instructor.email} verification '
				f'changed from {old_verification_status} '
				f'to {verification_status}.'
			),
			metadata={
				'previous_status':
					old_verification_status,
				'new_status':
					verification_status,
			}
		)

		return Response(
			{
				'detail':
					'Instructor verification status '
					'updated successfully.',
				'instructor': {
					'id': instructor.id,
					'name': instructor.name,
					'email': instructor.email,
					'verification_status':
						instructor.verification_status,
					'verified_by': (
						request.user.id
						if verification_status
						== 'verified'
						else None
					),
					'verified_at':
						instructor.verified_at,
				},
			},
			status=status.HTTP_200_OK
		)


# =========================================================
# Super Admin - Role & Permission Management
# =========================================================

class SuperAdminPermissionListAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	List all permissions available in the system.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		self.check_super_admin(request)

		permissions = Permission.objects.all().order_by('id')

		results = [
			{
				'id': permission.id,
				'name': permission.name,
				'description': permission.description,
			}
			for permission in permissions
		]

		return Response(
			{
				'count': len(results),
				'results': results,
			},
			status=status.HTTP_200_OK
		)


class SuperAdminRolePermissionListAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	List all roles together with their assigned permissions.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		self.check_super_admin(request)

		roles = Role.objects.all().order_by('id')

		results = []

		for role in roles:
			role_permissions = (
				RolePermission.objects
				.filter(role=role)
				.select_related('permission')
				.order_by('permission__id')
			)

			permissions = [
				{
					'id': item.permission.id,
					'name': item.permission.name,
					'description':
						item.permission.description,
				}
				for item in role_permissions
			]

			results.append({
				'id': role.id,
				'name': role.name,
				'description': role.description,
				'permissions': permissions,
			})

		return Response(
			{
				'count': len(results),
				'results': results,
			},
			status=status.HTTP_200_OK
		)


class SuperAdminRolePermissionDetailAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	Retrieve or replace permissions assigned to one role.

	PATCH body:

	{
		"permissions": [
			"manage_courses",
			"manage_payments"
		]
	}

	PATCH replaces the role's current permission set.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request, role_id):
		self.check_super_admin(request)

		try:
			role = Role.objects.get(pk=role_id)

		except Role.DoesNotExist:
			raise NotFound('Role not found.')

		role_permissions = (
			RolePermission.objects
			.filter(role=role)
			.select_related('permission')
			.order_by('permission__id')
		)

		permissions = [
			{
				'id': item.permission.id,
				'name': item.permission.name,
				'description':
					item.permission.description,
			}
			for item in role_permissions
		]

		return Response(
			{
				'id': role.id,
				'name': role.name,
				'description': role.description,
				'permissions': permissions,
			},
			status=status.HTTP_200_OK
		)

	@transaction.atomic
	def patch(self, request, role_id):
		self.check_super_admin(request)

		try:
			role = Role.objects.get(pk=role_id)

		except Role.DoesNotExist:
			raise NotFound('Role not found.')

		permission_names = request.data.get('permissions')

		if permission_names is None:
			return Response(
				{
					'detail': 'permissions is required.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if not isinstance(permission_names, list):
			return Response(
				{
					'detail':
						'permissions must be a list '
						'of permission names.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if len(permission_names) != len(
			set(permission_names)
		):
			return Response(
				{
					'detail':
						'Duplicate permissions are not allowed.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		if not all(
			isinstance(permission_name, str)
			for permission_name in permission_names
		):
			return Response(
				{
					'detail':
						'Every permission must be '
						'provided as a name.'
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		permissions = Permission.objects.filter(
			name__in=permission_names
		)

		found_names = set(
			permissions.values_list(
				'name',
				flat=True
			)
		)

		requested_names = set(permission_names)

		invalid_permissions = sorted(
			requested_names - found_names
		)

		if invalid_permissions:
			return Response(
				{
					'detail':
						'One or more permissions are invalid.',
					'invalid_permissions':
						invalid_permissions,
					'available_permissions': list(
						Permission.objects.order_by('id')
						.values_list('name', flat=True)
					),
				},
				status=status.HTTP_400_BAD_REQUEST
			)

		old_permissions = list(
			RolePermission.objects
			.filter(role=role)
			.order_by('permission__id')
			.values_list(
				'permission__name',
				flat=True
			)
		)

		RolePermission.objects.filter(
			role=role
		).delete()

		RolePermission.objects.bulk_create([
			RolePermission(
				role=role,
				permission=permission
			)
			for permission in permissions
		])

		updated_permissions = (
			RolePermission.objects
			.filter(role=role)
			.select_related('permission')
			.order_by('permission__id')
		)

		new_permissions = [
			item.permission.name
			for item in updated_permissions
		]

		_create_audit_log(
			request=request,
			action='permission_change',
			target_type='role',
			target_id=role.id,
			target_display=role.name,
			description=(
				f'Permissions for role {role.name} '
				f'were updated.'
			),
			metadata={
				'previous_permissions':
					old_permissions,
				'new_permissions':
					new_permissions,
			}
		)

		return Response(
			{
				'detail':
					'Role permissions updated successfully.',
				'role': {
					'id': role.id,
					'name': role.name,
					'permissions': [
						{
							'id': item.permission.id,
							'name': item.permission.name,
						}
						for item in updated_permissions
					],
				},
			},
			status=status.HTTP_200_OK
		)


# =========================================================
# Super Admin - Audit Records
# =========================================================

class SuperAdminAuditLogListAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	List audit records for Super Admin.

	Optional query parameters:
	- action
	- target_type
	- actor_id
	- search
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		self.check_super_admin(request)

		audit_logs = (
			AuditLog.objects
			.select_related('actor')
			.all()
			.order_by('-created_at')
		)

		action = request.query_params.get('action')
		target_type = request.query_params.get('target_type')
		actor_id = request.query_params.get('actor_id')
		search = request.query_params.get('search')

		if action:
			valid_actions = {
				choice[0]
				for choice in AuditLog.ACTION_CHOICES
			}

			if action not in valid_actions:
				return Response(
					{
						'detail': 'Invalid audit action.',
						'available_actions': sorted(valid_actions),
					},
					status=status.HTTP_400_BAD_REQUEST
				)

			audit_logs = audit_logs.filter(action=action)

		if target_type:
			audit_logs = audit_logs.filter(
				target_type=target_type
			)

		if actor_id:
			try:
				actor_id = int(actor_id)

			except (TypeError, ValueError):
				return Response(
					{
						'detail':
							'actor_id must be a valid integer.'
					},
					status=status.HTTP_400_BAD_REQUEST
				)

			audit_logs = audit_logs.filter(
				actor_id=actor_id
			)

		if search:
			audit_logs = audit_logs.filter(
				Q(target_display__icontains=search)
				| Q(description__icontains=search)
				| Q(actor__name__icontains=search)
				| Q(actor__email__icontains=search)
			)

		results = []

		for audit_log in audit_logs:
			results.append(
				self._serialize_audit_log(audit_log)
			)

		return Response(
			{
				'count': len(results),
				'results': results,
			},
			status=status.HTTP_200_OK
		)

	def _serialize_audit_log(self, audit_log):
		return {
			'id': audit_log.id,
			'actor': (
				{
					'id': audit_log.actor.id,
					'name': audit_log.actor.name,
					'email': audit_log.actor.email,
					'role': (
						audit_log.actor.role.name
						if audit_log.actor.role
						else None
					),
				}
				if audit_log.actor
				else None
			),
			'action': audit_log.action,
			'target_type': audit_log.target_type,
			'target_id': audit_log.target_id,
			'target_display': audit_log.target_display,
			'description': audit_log.description,
			'metadata': audit_log.metadata,
			'ip_address': audit_log.ip_address,
			'created_at': audit_log.created_at,
		}


class SuperAdminAuditLogDetailAPIView(
	SuperAdminRequiredMixin,
	APIView
):
	"""
	Retrieve one audit record.

	Audit records are read-only and cannot be modified
	or deleted through this API.
	"""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request, audit_log_id):
		self.check_super_admin(request)

		try:
			audit_log = (
				AuditLog.objects
				.select_related(
					'actor',
					'actor__role'
				)
				.get(pk=audit_log_id)
			)

		except AuditLog.DoesNotExist:
			raise NotFound('Audit record not found.')

		return Response(
			{
				'id': audit_log.id,
				'actor': (
					{
						'id': audit_log.actor.id,
						'name': audit_log.actor.name,
						'email': audit_log.actor.email,
						'role': (
							audit_log.actor.role.name
							if audit_log.actor.role
							else None
						),
					}
					if audit_log.actor
					else None
				),
				'action': audit_log.action,
				'target_type': audit_log.target_type,
				'target_id': audit_log.target_id,
				'target_display':
					audit_log.target_display,
				'description': audit_log.description,
				'metadata': audit_log.metadata,
				'ip_address': audit_log.ip_address,
				'created_at': audit_log.created_at,
			},
			status=status.HTTP_200_OK
		)