from django.db.models import Q, QuerySet
from django.utils import timezone

from rest_framework import generics, status
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db import transaction
from django.utils import timezone
from decimal import Decimal

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.exceptions import PermissionDenied, NotFound

from .models import (
    Chapter,
    Course,
    District,
    Enrollment,
    Grade,
    Lesson,
    LessonProgress,
    Municipality,
    Province,
    Question,
    QuestionOption,
    Quiz,
    QuizAttempt,
    School,
    StudentAnswer,
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
    InstructorRegistrationSerializer,
    LessonProgressSerializer,
    LessonSerializer,
    LoginSerializer,
    MunicipalitySerializer,
    ProvinceSerializer,
    QuestionManagementSerializer,
    QuestionOptionManagementSerializer,
    QuizManagementSerializer,
    QuizStudentSerializer,
    ResetPasswordSerializer,
    SchoolSerializer,
    StudentRegistrationSerializer,
    SubjectSerializer,
    TopicSerializer,
    VerifyPasswordResetOTPSerializer,
	QuizAttemptSerializer,
	QuizSubmitSerializer,
    InstructorQuizResultSerializer,

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
        course = Course.objects.filter(
            pk=course_id
        ).first()

        if course is None:
            return Response(
                {'detail': 'Course not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = EnrollCourseSerializer(
            data={},
            context={
                'course': course,
                'request': request,
            }
        )
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
        ).select_related(
            'course'
        ).order_by('-enrolled_at')


class CompleteLessonAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, lesson_id):
        lesson = Lesson.objects.filter(
            pk=lesson_id
        ).select_related(
            'course',
            'topic__chapter'
        ).first()

        if lesson is None:
            return Response(
                {'detail': 'Lesson not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

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
                    {
                        'detail': (
                            'You must be enrolled in this '
                            'course to access this lesson.'
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            enrollment = Enrollment.objects.filter(
                student=student,
                course=lesson.course
            ).first()

        elif lesson.topic is not None:
            student_grade_id = getattr(
                getattr(
                    student,
                    'student_profile',
                    None
                ),
                'grade_id',
                None
            )

            if student_grade_id != lesson.topic.chapter.grade_id:
                return Response(
                    {
                        'detail': (
                            'This lesson is not part of your grade.'
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        else:
            return Response(
                {
                    'detail': (
                        'This lesson is not attached to '
                        'any course or topic.'
                    )
                },
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

        return Response(
            LessonProgressSerializer(progress).data,
            status=status.HTTP_200_OK,
        )


class CourseProgressAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, course_id):
        course = Course.objects.filter(
            pk=course_id
        ).first()

        if course is None:
            return Response(
                {'detail': 'Course not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        student = request.user

        enrollment = Enrollment.objects.filter(
            student=student,
            course=course,
            status__in=['active', 'completed'],
        ).first()

        if enrollment is None:
            return Response(
                {
                    'detail': (
                        'You must be enrolled in this '
                        'course to view progress.'
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        total_lessons = Lesson.objects.filter(
            course=course
        ).count()

        completed_lessons = LessonProgress.objects.filter(
            student=student,
            lesson__course=course,
            is_completed=True,
        ).count()

        progress_percentage = (
            round(
                (completed_lessons / total_lessons) * 100,
                2
            )
            if total_lessons > 0
            else 0.0
        )

        is_completed = (
            total_lessons > 0
            and completed_lessons == total_lessons
        )

        if (
            is_completed
            and enrollment.status != 'completed'
        ):
            enrollment.status = 'completed'
            enrollment.completed_at = timezone.now()
            enrollment.save(
                update_fields=[
                    'status',
                    'completed_at',
                ]
            )

        return Response(
            {
                'course_id': course.id,
                'total_lessons': total_lessons,
                'completed_lessons': completed_lessons,
                'progress_percentage': progress_percentage,
                'is_completed': is_completed,
            },
            status=status.HTTP_200_OK,
        )


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
	# =========================================================
# Submit Quiz Attempt
# =========================================================

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
                {'detail': 'This quiz attempt has already been submitted.'},
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
                {'detail': 'This quiz has no questions.'},
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

        # Student must answer every question
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
                {'detail': 'Quiz total marks must be greater than zero.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        question_map = {
            question.id: question
            for question in questions
        }

        score = Decimal('0.00')

        answers_to_create = []

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

        percentage = (
            score / Decimal(str(total_marks))
        ) * Decimal('100')

        percentage = percentage.quantize(
            Decimal('0.01')
        )

        is_passed = (
            percentage >=
            Decimal(str(attempt.quiz.pass_percentage))
        )

        StudentAnswer.objects.bulk_create(
            answers_to_create
        )

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

        return Response(
            {
                'detail': 'Quiz submitted successfully.',
                'attempt': QuizAttemptSerializer(
                    attempt
                ).data,
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