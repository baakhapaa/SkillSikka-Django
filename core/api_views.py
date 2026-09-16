from django.db.models import QuerySet
from rest_framework.authentication import SessionAuthentication
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Chapter,
    Course,
    District,
    Grade,
    Lesson,
    Municipality,
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
    ForgotPasswordSerializer,
    GradeSerializer,
    InstructorRegistrationSerializer,
    LessonSerializer,
    LoginSerializer,
    MunicipalitySerializer,
    ProvinceSerializer,
    ResetPasswordSerializer,
    SchoolSerializer,
    StudentRegistrationSerializer,
    SubjectSerializer,
    TopicSerializer,
    VerifyPasswordResetOTPSerializer,
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

        # -------------------------------------------------
        # COURSE VISIBILITY
        # -------------------------------------------------
        # Admin:
        #   Can see all courses.
        #
        # Instructor:
        #   Can see all published courses + their own drafts.
        #
        # Student / other users:
        #   Can see published courses only.
        # -------------------------------------------------

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

        # -------------------------------------------------
        # FILTERS
        # -------------------------------------------------

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

        # Admin can access all courses.
        if _is_admin(user):
            return queryset

        # Instructor can access:
        # 1. All published courses
        # 2. Their own draft courses
        if _is_instructor(user):
            return queryset.filter(
                Q(is_published=True)
                | Q(instructor=user)
            )

        # Students/other users can only access
        # published courses.
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

        # Course is required by LessonSerializer.
        # Instructor can only add lessons to their own course.
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

        # If course is being changed during update,
        # make sure instructor owns the new course too.
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