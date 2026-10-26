"""Documentation for course/student contracts; no runtime response changes."""
from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import serializers

from .serializers import (CertificateSerializer, CourseProgressSerializer,
    EnrollmentSerializer, HomeCourseSerializer, InitiatePaymentSerializer, LearningCourseSerializer,
    PaymentSerializer, PublicInstructorSerializer, LessonProgressSerializer, QuizAttemptSerializer)
from .event_serializers import EventSerializer
from .advertisement_serializers import AdvertisementDisplaySerializer


class VerifiedJWTScheme(SimpleJWTScheme):
    target_class = 'core.authentication.EmailVerifiedJWTAuthentication'
    name = 'verifiedJwtAuth'


class CourseErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()


class QuizLimitErrorSerializer(CourseErrorSerializer):
    max_attempts = serializers.IntegerField()
    attempts_used = serializers.IntegerField()


class LearningStatsSerializer(serializers.Serializer):
    courses_completed = serializers.IntegerField()
    day_streak = serializers.IntegerField()
    hours_learned = serializers.FloatField(allow_null=True)


class MyLearningResponseSerializer(serializers.Serializer):
    continue_learning = LearningCourseSerializer(allow_null=True)
    courses = LearningCourseSerializer(many=True)
    completed_courses = LearningCourseSerializer(many=True)
    stats = LearningStatsSerializer()
    certificates = CertificateSerializer(many=True)


class HomeResponseSerializer(serializers.Serializer):
    featured_courses = HomeCourseSerializer(many=True)
    recommended_courses = HomeCourseSerializer(many=True)
    skill_courses = HomeCourseSerializer(many=True)
    events = EventSerializer(many=True)
    advertisements = AdvertisementDisplaySerializer(many=True)
    top_instructors = PublicInstructorSerializer(many=True)


class PaymentInitiationResponseSerializer(PaymentSerializer):
    payment_url = serializers.URLField(read_only=True)

    class Meta(PaymentSerializer.Meta):
        fields = PaymentSerializer.Meta.fields + ['payment_url']


def document_course_views(views):
    errors = {400: CourseErrorSerializer, 403: CourseErrorSerializer, 404: CourseErrorSerializer}
    specs = {
        'CompleteLessonAPIView': {'post': extend_schema(request=None, responses={200: LessonProgressSerializer, **errors})},
        'CheckCourseCertificateAPIView': {'post': extend_schema(request=None, responses={200: CertificateSerializer, 201: CertificateSerializer, **errors})},
        'CheckGradeCertificateAPIView': {'post': extend_schema(request=None, responses={200: CertificateSerializer, 201: CertificateSerializer, **errors})},
        'StartQuizAttemptAPIView': {'post': extend_schema(request=None, responses={200: QuizAttemptSerializer, 201: QuizAttemptSerializer, 400: QuizLimitErrorSerializer})},
        'EnrollCourseAPIView': {'post': extend_schema(request=None, responses={201: EnrollmentSerializer, **errors})},
        'CourseProgressAPIView': {'get': extend_schema(responses={200: CourseProgressSerializer, **errors}, description='Skill progress requires active/completed enrollment. Academic progress uses the active student’s matching grade, without enrollment.')},
        'MyLearningAPIView': {'get': extend_schema(responses={200: MyLearningResponseSerializer}, description='Enrollment-based skill learning dashboard. Academic progress is available through course progress.')},
        'HomeFeedAPIView': {'get': extend_schema(responses={200: HomeResponseSerializer}, description='Student dashboard with deterministic recommendations. Available without a Gemini/network request.')},
        'InitiatePaymentAPIView': {'post': extend_schema(request=InitiatePaymentSerializer, responses={201: PaymentInitiationResponseSerializer}, description='Existing payment initiation response. payment_url opens the provider checkout.')},
        'CourseListCreateAPIView': {'get': extend_schema(parameters=[
            OpenApiParameter('search', str, description='Case-insensitive title/description search; blank means no filter.'),
            OpenApiParameter('ordering', str, enum=['created_at', '-created_at', 'title', '-title', 'average_rating', '-average_rating', 'price', '-price'], description='Default and invalid-value fallback: -created_at. pk breaks ties.'),
            OpenApiParameter('skill_category', int),
            *[OpenApiParameter(name, int) for name in ['subject', 'grade', 'instructor']],
            OpenApiParameter('course_type', str, enum=['academic', 'skill']),
            OpenApiParameter('is_paid', bool), OpenApiParameter('is_published', bool),
        ])},
    }
    for name, methods in specs.items():
        extend_schema_view(**methods)(views[name])
