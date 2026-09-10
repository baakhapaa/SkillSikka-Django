from django.db.models import QuerySet
from django.utils import timezone

from rest_framework import generics, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
	Course,
	District,
	Enrollment,
	Grade,
	Lesson,
	LessonProgress,
	Municipality,
	Province,
	School,
	User,
)

from .serializers import (
	DistrictSerializer,
	EnrollCourseSerializer,
	EnrollmentSerializer,
	ForgotPasswordSerializer,
	GradeSerializer,
	InstructorRegistrationSerializer,
	LessonProgressSerializer,
	LoginSerializer,
	MunicipalitySerializer,
	ProvinceSerializer,
	ResetPasswordSerializer,
	SchoolSerializer,
	StudentRegistrationSerializer,
	VerifyPasswordResetOTPSerializer,
)


class RegistrationResponseMixin:
	serializer_class = None
	role_name = None

	def post(self, request, *args, **kwargs):
		serializer = self.serializer_class(data=request.data)
		serializer.is_valid(raise_exception=True)

		user = serializer.save()
		refresh = RefreshToken.for_user(user)

		return Response({
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
		}, status=status.HTTP_201_CREATED)


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


class LoginAPIView(APIView):
	def post(self, request):
		serializer = LoginSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)

		user = serializer.validated_data['user']
		refresh = RefreshToken.for_user(user)

		return Response({
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
		}, status=status.HTTP_200_OK)


class CurrentUserAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		user = request.user

		return Response({
			'id': str(user.id),
			'email': user.email,
			'name': user.name,
			'role': user.role.name if user.role else None,
			'verification_status': user.verification_status,
			'onboarding_completed': user.onboarding_completed,
			'is_active': user.is_active,
		}, status=status.HTTP_200_OK)


class LogoutAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request):
		refresh_token = request.data.get('refresh')

		if not refresh_token:
			return Response({
				'detail': 'Refresh token is required.'
			}, status=status.HTTP_400_BAD_REQUEST)

		try:
			token = RefreshToken(refresh_token)
			token.blacklist()

			return Response({
				'detail': 'Logged out successfully.'
			}, status=status.HTTP_200_OK)

		except TokenError:
			return Response({
				'detail': 'Invalid or expired refresh token.'
			}, status=status.HTTP_400_BAD_REQUEST)


class ForgotPasswordAPIView(APIView):
	def post(self, request):
		serializer = ForgotPasswordSerializer(
			data=request.data
		)

		serializer.is_valid(raise_exception=True)
		serializer.save()

		return Response({
			'detail': (
				'If an account exists with this email, '
				'a password reset OTP has been sent.'
			)
		}, status=status.HTTP_200_OK)


class VerifyPasswordResetOTPAPIView(APIView):
	def post(self, request):
		serializer = VerifyPasswordResetOTPSerializer(
			data=request.data
		)

		serializer.is_valid(raise_exception=True)

		return Response({
			'detail': 'OTP verified successfully.',
			'reset_token':
				serializer.validated_data['reset_token'],
		}, status=status.HTTP_200_OK)


class ResetPasswordAPIView(APIView):
	def post(self, request):
		serializer = ResetPasswordSerializer(
			data=request.data
		)

		serializer.is_valid(raise_exception=True)
		serializer.save()

		return Response({
			'detail': 'Password reset successfully.'
		}, status=status.HTTP_200_OK)


class RoleListAPIView(APIView):
	def get(self, request):
		return Response([
			{
				'value': 'student',
				'label': 'Student'
			},
			{
				'value': 'instructor',
				'label': 'Instructor'
			},
		])


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
				province_id=self.request.query_params[
					'province_id'
				]
			)

		elif (
			self.lookup_model is Municipality
			and self.request.query_params.get('district_id')
		):
			queryset = queryset.filter(
				district_id=self.request.query_params[
					'district_id'
				]
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