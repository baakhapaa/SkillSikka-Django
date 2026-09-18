from django.db.models import Q, QuerySet
from django.utils import timezone

from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
	Chapter,
	Course,
	District,
	Enrollment,
	Grade,
	Lesson,
	LessonProgress,
	Municipality,
	Payment,
	Province,
	School,
	Subject,
	Topic,
	User,
)

from .serializers import (
	ChapterSerializer,
	CourseSerializer,
	DistrictSerializer,
	EnrollCourseSerializer,
	EnrollmentSerializer,
	ForgotPasswordSerializer,
	GradeSerializer,
	InitiatePaymentSerializer,
	InstructorRegistrationSerializer,
	LessonProgressSerializer,
	LessonSerializer,
	LoginSerializer,
	MunicipalitySerializer,
	PaymentSerializer,
	ProvinceSerializer,
	ResetPasswordSerializer,
	SchoolSerializer,
	StudentRegistrationSerializer,
	SubjectSerializer,
	TopicSerializer,
	VerifyPasswordResetOTPSerializer,
	VerifyPaymentSerializer,
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