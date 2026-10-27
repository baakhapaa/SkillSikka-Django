"""Nested Course data and efficient bootcamp catalogue loading."""
from django.db.models import Count, OuterRef, Prefetch, Subquery, prefetch_related_objects
from django.db.models.functions import Coalesce
from rest_framework import serializers
from .models import BootcampProfile, CourseInstructor, BootcampResource, BootcampDiscussion, User


class BootcampProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = BootcampProfile
        exclude = ['id', 'course']

    def validate(self, attrs):
        instance = self.instance
        start = attrs.get('starts_on', getattr(instance, 'starts_on', None))
        end = attrs.get('ends_on', getattr(instance, 'ends_on', None))
        if start and end and end < start:
            raise serializers.ValidationError({'ends_on': 'End date must not precede start date.'})
        return attrs


class CourseInstructorInputSerializer(serializers.Serializer):
    instructor = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(
        role__name='instructor', is_active=True, verification_status='verified'))
    role = serializers.ChoiceField(choices=CourseInstructor.ROLE_CHOICES)
    order = serializers.IntegerField(min_value=0, max_value=32767, default=0)


class CourseInstructorDisplaySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='instructor_id')
    name = serializers.CharField(source='instructor.name')
    profile_photo_url = serializers.SerializerMethodField()

    def get_profile_photo_url(self, obj) -> str | None:
        photo = obj.instructor.profile_photo_src
        request = self.context.get('request')
        return request.build_absolute_uri(photo) if photo and request else photo

    class Meta:
        model = CourseInstructor
        fields = ['id', 'name', 'role', 'profile_photo_url']


def with_bootcamp_data(queryset, *, detail=False):
    queryset = queryset.select_related('bootcamp_profile')
    if detail:
        resources = BootcampResource.objects.filter(course=OuterRef('pk')).order_by().values('course')
        discussions = BootcampDiscussion.objects.filter(course=OuterRef('pk'), parent=None, is_hidden=False).order_by().values('course')
        queryset = queryset.annotate(
            resources_count=Coalesce(Subquery(resources.annotate(n=Count('pk')).values('n')), 0),
            discussions_count=Coalesce(Subquery(discussions.annotate(n=Count('pk')).values('n')), 0))
    return queryset


def load_bootcamp_rosters(courses):
    bootcamps = [course for course in courses if course.course_type == 'bootcamp']
    if bootcamps:
        prefetch_related_objects(bootcamps, Prefetch('instructors', queryset=CourseInstructor.objects.select_related('instructor')))


class CourseListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        courses = list(data.all() if hasattr(data, 'all') else data)
        load_bootcamp_rosters(courses)
        return super().to_representation(courses)
