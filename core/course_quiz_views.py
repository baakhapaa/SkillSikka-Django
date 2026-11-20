from django.db.models import Count, Exists, Max, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated

from .authentication import EmailVerifiedJWTAuthentication
from .course_access import CourseAPIError, is_course_manager, require_course_access
from .models import Course, Question, Quiz, QuizAttempt


class CourseQuizSerializer(serializers.ModelSerializer):
    attempts_used = serializers.IntegerField(read_only=True)
    best_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True, allow_null=True)
    is_passed = serializers.BooleanField(read_only=True)
    question_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'section', 'question_count', 'pass_percentage', 'max_attempts',
                  'time_limit_seconds', 'attempts_used', 'best_percentage', 'is_passed']
        read_only_fields = fields


class CourseQuizListAPIView(generics.ListAPIView):
    authentication_classes = [EmailVerifiedJWTAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = CourseQuizSerializer
    pagination_class = None

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Quiz.objects.none()
        course = Course.objects.filter(pk=self.kwargs['course_id']).first()
        if course is None:
            raise CourseAPIError('COURSE_NOT_FOUND', 'Course not found.', 404)
        require_course_access(self.request.user, course)
        quizzes = Quiz.objects.filter(course=course)
        if not is_course_manager(self.request.user, course):
            quizzes = quizzes.filter(is_published=True)
        completed = Q(attempts__student=self.request.user, attempts__completed_at__isnull=False)
        # A subquery, because joining questions next to attempts would multiply both counts.
        questions = Question.objects.filter(quiz=OuterRef('pk')).order_by().values('quiz')
        return quizzes.annotate(
            question_count=Coalesce(Subquery(questions.annotate(value=Count('pk')).values('value')), 0),
            attempts_used=Count('attempts', filter=completed),
            best_percentage=Max('attempts__percentage', filter=completed),
            is_passed=Exists(QuizAttempt.objects.filter(quiz=OuterRef('pk'), student=self.request.user,
                completed_at__isnull=False, is_passed=True)),
        ).order_by('pk')
