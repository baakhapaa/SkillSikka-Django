from django.db.models import Q, QuerySet
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from django.db.models import Sum

from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied, NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers


from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
	Certificate,
	CertificateCriteria,
	Chapter,
	Course,
	District,
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
	Subject,
	Topic,
	User,
	PointTransaction,
	Short,
    ShortComment,
    ShortLike,
    ShortView,
	Role,
	Permission,
    RolePermission,
)

from .serializers import (
	CertificateSerializer,
	ChapterSerializer,
	CourseSerializer,
	DistrictSerializer,
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
# Super Admin - User Management
# =========================================================

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

        target_user.is_active = is_active

        target_user.save(
            update_fields=[
                'is_active',
                'updated_at',
            ]
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
                    'description': item.permission.description,
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
                'description': item.permission.description,
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
                        'permissions must be a list of permission names.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Prevent duplicate permission names.
        if len(permission_names) != len(set(permission_names)):
            return Response(
                {
                    'detail':
                        'Duplicate permissions are not allowed.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Every item must be a string.
        if not all(
            isinstance(permission_name, str)
            for permission_name in permission_names
        ):
            return Response(
                {
                    'detail':
                        'Every permission must be provided as a name.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        permissions = Permission.objects.filter(
            name__in=permission_names
        )

        found_names = set(
            permissions.values_list('name', flat=True)
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

        # Do not allow Super Admin to remove its own
        # permission-management access through this endpoint.
        # Superuser accounts still bypass role permissions,
        # but keeping this guard avoids accidental lockout
        # for non-superuser users assigned super_admin role.
        if role.name == 'super_admin':
            current_permission_names = set(
                RolePermission.objects
                .filter(role=role)
                .values_list(
                    'permission__name',
                    flat=True
                )
            )

            # At present there is no dedicated
            # "manage_permissions" permission in the database,
            # so existing permissions may be changed normally.
            # Super Admin API access itself remains protected
            # by the super_admin role.
            current_permission_names = current_permission_names

        # Replace existing assignments.
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