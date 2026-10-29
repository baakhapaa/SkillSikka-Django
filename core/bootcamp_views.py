"""Course subresources: resources (optionally per lesson) and discussions."""
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from rest_framework import generics, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from .authentication import EmailVerifiedJWTAuthentication
from .api_views import _is_admin, _is_instructor
from .course_access import CourseAPIError, is_course_manager, require_course_access
from .course_pagination import CoursePagination
from .models import Course, CourseResource, CourseDiscussion, DiscussionLike


def course_for(request, course_id, *, access=False):
    """Any course, for the subresource endpoints.

    **Reading is open to any authenticated user** on a published course — the
    player's Q&A tab has to render for a preview watcher who has not enrolled.
    The resources endpoint asks for `access=True` on top of this, because a file
    is the course's material rather than a public conversation.
    **Writing requires access**: the course's owner, anyone on its instructor
    roster, an administrator, or whatever `require_course_access` grants — an
    active/completed enrollment for a skill or bootcamp course, grade
    eligibility for an academic one. That also covers `pending_payment`, which
    is deliberately not enough.

    The roster matters: a bootcamp's `coach` is not its owner and is not
    enrolled, so an owner-only check would mute every teaching assistant.
    """
    course = Course.objects.filter(pk=course_id).first()
    if course is None:
        raise CourseAPIError('COURSE_NOT_FOUND', 'Course not found.', 404)
    if not _is_admin(request.user) and not course.is_published:
        raise CourseAPIError('COURSE_NOT_PUBLISHED', 'This course is not published.', 403)
    if access and not (
        _is_admin(request.user)
        or course.instructor_id == request.user.pk
        or course.instructors.filter(instructor_id=request.user.pk).exists()
    ):
        require_course_access(request.user, course, managers=False)
    return course


class CourseResourceSerializer(serializers.ModelSerializer):
    lesson_title = serializers.CharField(source='lesson.title', read_only=True, default=None)

    class Meta:
        model = CourseResource
        fields = ['id', 'course', 'lesson', 'lesson_title', 'section', 'title', 'file_format', 'file_url', 'file_size_bytes', 'order', 'created_at']
        read_only_fields = ['id', 'course', 'created_at']

    def validate(self, attrs):
        """A resource may not point at a lesson belonging to another course.

        `Model.clean()` says the same thing, but DRF never calls `full_clean`,
        so without this the API would happily publish one course's files under
        another course's tab and only the shell would complain.
        """
        lesson = attrs.get('lesson')
        course_id = self.context['view'].kwargs.get('course_id')
        if lesson is not None and course_id and lesson.course_id and lesson.course_id != int(course_id):
            raise serializers.ValidationError({'lesson': 'That lesson belongs to a different course.'})
        return attrs


class CourseEndpointMixin:
    authentication_classes = [EmailVerifiedJWTAuthentication]
    permission_classes = [IsAuthenticated]


def require_course_manager(user, course):
    """Who may change a course's subresources: admin, owner, or roster instructor.

    `course_for(access=True)` is deliberately *not* enough here — it also passes
    an enrolled student, which is right for reading and for posting a comment,
    and wrong for attaching or deleting a file.

    `is_course_manager` covers the admin and the owner; the roster half is added
    here because a bootcamp's `coach` teaches the course without owning it.
    """
    if is_course_manager(user, course) or course.instructors.filter(instructor_id=user.pk).exists():
        return
    raise CourseAPIError('NOT_COURSE_OWNER', 'Only the course owner or an administrator can change its resources.', 403)


@extend_schema_view(
    get=extend_schema(description='Course resources, optionally per lesson. Active/completed enrollment required for students; administrators, the owner and roster instructors may read.'),
    post=extend_schema(description='Course owner or administrator. URLs only; upload the file through POST /courses/{id}/assets/ with kind="resource" first.'))
class CourseResourceListAPIView(CourseEndpointMixin, generics.ListCreateAPIView):
    serializer_class = CourseResourceSerializer
    pagination_class = None

    def get_queryset(self):
        course = course_for(self.request, self.kwargs['course_id'], access=True)
        queryset = CourseResource.objects.filter(course=course).select_related('lesson')
        # `?lesson=<id>` is how the player asks for one lesson's files without
        # pulling the whole pack; the tab also filters locally because it
        # already holds the list.
        lesson_id = self.request.query_params.get('lesson')
        if lesson_id:
            queryset = queryset.filter(lesson_id=lesson_id)
        return queryset

    def perform_create(self, serializer):
        course = course_for(self.request, self.kwargs['course_id'])
        require_course_manager(self.request.user, course)
        serializer.save(course=course)

    def create(self, request, *args, **kwargs):
        require_course_manager(request.user, course_for(request, kwargs['course_id']))
        return super().create(request, *args, **kwargs)


@extend_schema_view(patch=extend_schema(description='Course owner or administrator.'), delete=extend_schema(description='Course owner or administrator.'))
class CourseResourceDetailAPIView(CourseEndpointMixin, generics.UpdateAPIView, generics.DestroyAPIView):
    serializer_class = CourseResourceSerializer
    http_method_names = ['patch', 'delete', 'options']
    lookup_url_kwarg = 'resource_id'

    def get_queryset(self):
        course = course_for(self.request, self.kwargs['course_id'])
        require_course_manager(self.request.user, course)
        return CourseResource.objects.filter(course=course)


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
        model = CourseDiscussion
        fields = ['id', 'course', 'parent', 'author', 'body', 'likes_count', 'is_liked', 'is_mine', 'is_hidden', 'created_at']
        read_only_fields = fields


class CourseDiscussionSerializer(DiscussionReplySerializer):
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
    rows = CourseDiscussion.objects.filter(course=course).select_related('author__role', 'author__student_profile__grade')
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
    get=extend_schema(responses=CourseDiscussionSerializer(many=True), parameters=[OpenApiParameter('ordering', str, enum=['-created_at', 'created_at', '-likes_count'])], description='Authenticated read of a published course discussion; enrollment is not required. Inline replies capped at 50; replies_count counts visible replies. Hidden threads excluded except for administrators.'),
    post=extend_schema(request=DiscussionCreateSerializer, responses={201: CourseDiscussionSerializer}, description='Active/completed students, the course instructor or an admin may participate. Errors: BODY_REQUIRED, BODY_TOO_LONG, DISCUSSION_NOT_FOUND, NOT_ENROLLED, COURSE_NOT_PUBLISHED. One reply level only.'))
class CourseDiscussionListAPIView(CourseEndpointMixin, generics.ListCreateAPIView):
    serializer_class = CourseDiscussionSerializer
    pagination_class = CoursePagination

    def get_queryset(self):
        course = course_for(self.request, self.kwargs['course_id'])
        ordering = self.request.query_params.get('ordering', '-created_at')
        if ordering not in ['-created_at', 'created_at', '-likes_count']:
            ordering = '-created_at'
        return discussion_with_replies(self.request, course).filter(parent=None).order_by(ordering, 'pk')

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        course = course_for(request, kwargs['course_id'], access=True)
        serializer = DiscussionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent_id = serializer.validated_data.get('parent')
        parent = find_discussion(request, course, parent_id) if parent_id else None
        if parent and parent.parent_id:
            raise CourseAPIError('DISCUSSION_NOT_FOUND', 'Replies must reference a top-level discussion.', 400)
        discussion = CourseDiscussion.objects.create(course=course, author=request.user,
            parent=parent, body=serializer.validated_data['body'])
        row = discussion_with_replies(request, course).get(pk=discussion.pk)
        return Response(self.get_serializer(row).data, status=201)


@extend_schema_view(
    patch=extend_schema(request=DiscussionModerationSerializer, responses=CourseDiscussionSerializer, description='Admin-only hide/unhide; ADMIN_ONLY (403). Body editing is unsupported.'),
    delete=extend_schema(responses={204: None}, description='Author or admin may delete. Deleting a parent cascades its replies and all associated likes.'))
class CourseDiscussionDetailAPIView(CourseEndpointMixin, generics.GenericAPIView):
    serializer_class = CourseDiscussionSerializer

    def delete(self, request, course_id, discussion_id):
        course = course_for(request, course_id)
        discussion = find_discussion(request, course, discussion_id)
        if discussion.author_id != request.user.pk and not _is_admin(request.user):
            raise PermissionDenied('Only the author or administrator may delete this discussion.')
        discussion.delete()
        return Response(status=204)

    def patch(self, request, course_id, discussion_id):
        # Moderation is admin-only on every course type. The old
        # `bootcamp_for(write=True)` answered `ADMIN_ONLY` here because the
        # endpoint only served bootcamps; now the check is stated rather than
        # inherited.
        if not _is_admin(request.user):
            raise CourseAPIError('ADMIN_ONLY', 'Only administrators can moderate discussions.', 403)
        course = course_for(request, course_id)
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
class CourseDiscussionLikeAPIView(CourseEndpointMixin, generics.GenericAPIView):
    serializer_class = DiscussionLikeResponseSerializer

    @transaction.atomic
    def post(self, request, course_id, discussion_id):
        return self.change(request, course_id, discussion_id, True)

    @transaction.atomic
    def delete(self, request, course_id, discussion_id):
        return self.change(request, course_id, discussion_id, False)

    def change(self, request, course_id, discussion_id, liked):
        course = course_for(request, course_id, access=True)
        discussion = find_discussion(request, course, discussion_id)
        # Serialize mutations on the discussion where the database supports row locks.
        CourseDiscussion.objects.select_for_update().get(pk=discussion.pk)
        if liked:
            DiscussionLike.objects.get_or_create(discussion=discussion, user=request.user)
        else:
            DiscussionLike.objects.filter(discussion=discussion, user=request.user).delete()
        return Response({'discussion_id': discussion.pk, 'is_liked': liked, 'likes_count': discussion.likes.count()})
