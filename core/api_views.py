from django.db.models import Count, Prefetch, Q, QuerySet
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from django.db.models import Sum

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
		serializer.is_valid(raise_exception=True)

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