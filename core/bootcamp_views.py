"""Bootcamp-only Course subresources; Course remains the enrollment/payment owner."""
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from .authentication import EmailVerifiedJWTAuthentication
from .api_views import _is_admin, _is_instructor
from .course_access import CourseAPIError, require_bootcamp_admin, require_course_access
from .course_pagination import CoursePagination
from .models import Course, BootcampResource, BootcampDiscussion, DiscussionLike


def bootcamp_for(request, course_id, *, write=False, access=False):
    if write:
        require_bootcamp_admin(request.user)
    course = Course.objects.filter(pk=course_id, course_type='bootcamp').first()
    if course is None:
        raise CourseAPIError('COURSE_NOT_FOUND', 'Bootcamp not found.', 404)
    if not _is_admin(request.user) and not course.is_published:
        raise CourseAPIError('COURSE_NOT_PUBLISHED', 'This course is not published.', 403)
    if access and not (_is_admin(request.user) or _is_instructor(request.user)):
        require_course_access(request.user, course, managers=False)
    return course


class BootcampResourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BootcampResource
        fields = ['id', 'course', 'section', 'title', 'file_format', 'file_url', 'file_size_bytes', 'order', 'created_at']
        read_only_fields = ['id', 'course', 'created_at']


class BootcampEndpointMixin:
    authentication_classes = [EmailVerifiedJWTAuthentication]
    permission_classes = [IsAuthenticated]


@extend_schema_view(
    get=extend_schema(description='Bootcamp resources. Active/completed enrollment required for students; administrators and authenticated instructors may read.'),
    post=extend_schema(description='Admin only. ADMIN_ONLY (403) for non-admin authors. URLs only; no binary upload.'))
class BootcampResourceListAPIView(BootcampEndpointMixin, generics.ListCreateAPIView):
    serializer_class = BootcampResourceSerializer
    pagination_class = None

    def get_queryset(self):
        course = bootcamp_for(self.request, self.kwargs['course_id'], write=self.request.method != 'GET', access=True)
        return BootcampResource.objects.filter(course=course)

    def perform_create(self, serializer):
        serializer.save(course=bootcamp_for(self.request, self.kwargs['course_id'], write=True))

    def create(self, request, *args, **kwargs):
        bootcamp_for(request, kwargs['course_id'], write=True)
        return super().create(request, *args, **kwargs)


@extend_schema_view(patch=extend_schema(description='Admin only (ADMIN_ONLY).'), delete=extend_schema(description='Admin only (ADMIN_ONLY).'))
class BootcampResourceDetailAPIView(BootcampEndpointMixin, generics.UpdateAPIView, generics.DestroyAPIView):
    serializer_class = BootcampResourceSerializer
    http_method_names = ['patch', 'delete', 'options']
    lookup_url_kwarg = 'resource_id'

    def get_queryset(self):
        course = bootcamp_for(self.request, self.kwargs['course_id'], write=True)
        return BootcampResource.objects.filter(course=course)


class DiscussionAuthorSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    profile_photo_url = serializers.SerializerMethodField()
    role_label = serializers.SerializerMethodField()

    def get_profile_photo_url(self, obj) -> str | None:
        photo = obj.profile_photo_src
        request = self.context.get('request')
        return request.build_absolute_uri(photo) if photo and request else photo

    def get_role_label(self, obj) -> str | None:
        role = getattr(obj.role, 'name', '')
        if role == 'instructor':
            return 'Instructor'
        if role == 'student':
            grade = getattr(getattr(obj, 'student_profile', None), 'grade', None)
            if grade:
                name = str(grade.name)
                return f'{name if name.lower().startswith("grade ") else "Grade " + name} Student'
            return 'Student'
        return 'Administrator' if obj.is_superuser or role == 'super_admin' else None


class DiscussionReplySerializer(serializers.ModelSerializer):
    author = DiscussionAuthorSerializer(read_only=True)
    likes_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.BooleanField(read_only=True)
    is_mine = serializers.SerializerMethodField()

    def get_is_mine(self, obj) -> bool:
        return obj.author_id == self.context['request'].user.pk

    class Meta:
        model = BootcampDiscussion
        fields = ['id', 'course', 'parent', 'author', 'body', 'likes_count', 'is_liked', 'is_mine', 'is_hidden', 'created_at']
        read_only_fields = fields


class BootcampDiscussionSerializer(DiscussionReplySerializer):
    replies_count = serializers.IntegerField(read_only=True)
    replies = DiscussionReplySerializer(source='inline_replies', many=True, read_only=True)

    class Meta(DiscussionReplySerializer.Meta):
        fields = DiscussionReplySerializer.Meta.fields + ['replies_count', 'replies']
        read_only_fields = fields


class DiscussionCreateSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, allow_null=True, trim_whitespace=True)
    parent = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate(self, attrs):
        if not attrs.get('body'):
            raise CourseAPIError('BODY_REQUIRED', 'Discussion body is required.')
        if len(attrs['body']) > 2000:
            raise CourseAPIError('BODY_TOO_LONG', 'Discussion body must be at most 2000 characters.')
        return attrs


class DiscussionModerationSerializer(serializers.Serializer):
    is_hidden = serializers.BooleanField(required=True)

    def validate(self, attrs):
        if set(self.initial_data) != {'is_hidden'}:
            raise serializers.ValidationError('Only is_hidden may be changed.')
        return attrs


class DiscussionLikeResponseSerializer(serializers.Serializer):
    discussion_id = serializers.IntegerField()
    is_liked = serializers.BooleanField()
    likes_count = serializers.IntegerField()


def discussion_rows(request, course):
    rows = BootcampDiscussion.objects.filter(course=course).select_related('author__role', 'author__student_profile__grade')
    if not _is_admin(request.user):
        rows = rows.filter(is_hidden=False).filter(Q(parent=None) | Q(parent__is_hidden=False))
    return rows.annotate(likes_count=Count('likes', distinct=True), is_liked=Exists(
        DiscussionLike.objects.filter(discussion=OuterRef('pk'), user=request.user)))


def discussion_with_replies(request, course):
    rows = discussion_rows(request, course)
    reply_filter = Q() if _is_admin(request.user) else Q(replies__is_hidden=False)
    return rows.annotate(replies_count=Count('replies', filter=reply_filter, distinct=True)).prefetch_related(
        Prefetch('replies', queryset=rows.order_by('created_at', 'pk')[:50], to_attr='inline_replies'))


def find_discussion(request, course, discussion_id):
    obj = discussion_rows(request, course).filter(pk=discussion_id).first()
    if obj is None:
        raise CourseAPIError('DISCUSSION_NOT_FOUND', 'Discussion not found.', 404)
    return obj


@extend_schema_view(
    get=extend_schema(responses=BootcampDiscussionSerializer(many=True), parameters=[OpenApiParameter('ordering', str, enum=['-created_at', 'created_at', '-likes_count'])], description='Authenticated read of published bootcamp discussions; enrollment is not required. Inline replies capped at 50; replies_count counts visible replies. Hidden threads excluded except for administrators.'),
    post=extend_schema(request=DiscussionCreateSerializer, responses={201: BootcampDiscussionSerializer}, description='Active/completed students, instructors or admins may participate. Errors: BODY_REQUIRED, BODY_TOO_LONG, DISCUSSION_NOT_FOUND, NOT_ENROLLED. One reply level only.'))
class BootcampDiscussionListAPIView(BootcampEndpointMixin, generics.ListCreateAPIView):
    serializer_class = BootcampDiscussionSerializer
    pagination_class = CoursePagination

    def get_queryset(self):
        course = bootcamp_for(self.request, self.kwargs['course_id'])
        ordering = self.request.query_params.get('ordering', '-created_at')
        if ordering not in ['-created_at', 'created_at', '-likes_count']:
            ordering = '-created_at'
        return discussion_with_replies(self.request, course).filter(parent=None).order_by(ordering, 'pk')

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        course = bootcamp_for(request, kwargs['course_id'], access=True)
        serializer = DiscussionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent_id = serializer.validated_data.get('parent')
        parent = find_discussion(request, course, parent_id) if parent_id else None
        if parent and parent.parent_id:
            raise CourseAPIError('DISCUSSION_NOT_FOUND', 'Replies must reference a top-level discussion.', 400)
        discussion = BootcampDiscussion.objects.create(course=course, author=request.user,
            parent=parent, body=serializer.validated_data['body'])
        row = discussion_with_replies(request, course).get(pk=discussion.pk)
        return Response(self.get_serializer(row).data, status=201)


@extend_schema_view(
    patch=extend_schema(request=DiscussionModerationSerializer, responses=BootcampDiscussionSerializer, description='Admin-only hide/unhide; ADMIN_ONLY (403). Body editing is unsupported.'),
    delete=extend_schema(responses={204: None}, description='Author or admin may delete. Deleting a parent cascades its replies and all associated likes.'))
class BootcampDiscussionDetailAPIView(BootcampEndpointMixin, generics.GenericAPIView):
    serializer_class = BootcampDiscussionSerializer

    def delete(self, request, course_id, discussion_id):
        course = bootcamp_for(request, course_id)
        discussion = find_discussion(request, course, discussion_id)
        if discussion.author_id != request.user.pk and not _is_admin(request.user):
            raise PermissionDenied('Only the author or administrator may delete this discussion.')
        discussion.delete()
        return Response(status=204)

    def patch(self, request, course_id, discussion_id):
        course = bootcamp_for(request, course_id, write=True)
        discussion = find_discussion(request, course, discussion_id)
        serializer = DiscussionModerationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        discussion.is_hidden = serializer.validated_data['is_hidden']
        discussion.save(update_fields=['is_hidden', 'updated_at'])
        row = discussion_with_replies(request, course).get(pk=discussion.pk)
        return Response(self.get_serializer(row).data)


@extend_schema_view(
    post=extend_schema(request=None, responses=DiscussionLikeResponseSerializer, description='Idempotently like a discussion. Participation access required. Wrong-course/hidden rows: DISCUSSION_NOT_FOUND.'),
    delete=extend_schema(request=None, responses=DiscussionLikeResponseSerializer, description='Idempotently remove own like.'))
class BootcampDiscussionLikeAPIView(BootcampEndpointMixin, generics.GenericAPIView):
    serializer_class = DiscussionLikeResponseSerializer

    @transaction.atomic
    def post(self, request, course_id, discussion_id):
        return self.change(request, course_id, discussion_id, True)

    @transaction.atomic
    def delete(self, request, course_id, discussion_id):
        return self.change(request, course_id, discussion_id, False)

    def change(self, request, course_id, discussion_id, liked):
        course = bootcamp_for(request, course_id, access=True)
        discussion = find_discussion(request, course, discussion_id)
        # Serialize mutations on the discussion where the database supports row locks.
        BootcampDiscussion.objects.select_for_update().get(pk=discussion.pk)
        if liked:
            DiscussionLike.objects.get_or_create(discussion=discussion, user=request.user)
        else:
            DiscussionLike.objects.filter(discussion=discussion, user=request.user).delete()
        return Response({'discussion_id': discussion.pk, 'is_liked': liked, 'likes_count': discussion.likes.count()})
