"""The Search screen: discover (before typing) and results (after typing).

Contract: docs/search-integration.md.
"""
from datetime import timedelta

from django.db.models import Case, Count, Exists, F, IntegerField, Max, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_views import _public_instructors, _shorts_with_saved_state
from .authentication import EmailVerifiedJWTAuthentication as JWTAuthentication
from .bootcamp_serializers import with_bootcamp_data
from .models import Course, Enrollment, LearningInterest, SearchQuery
from .serializers import HomeCourseSerializer, PublicInstructorSerializer, ShortSerializer


LIVE_STATUSES = ('active', 'completed')
SEARCH_TYPES = ('all', 'courses', 'creators', 'shorts')
MAX_QUERY_LENGTH = 100
# Words beyond this are ignored; each word adds a condition to every query.
MAX_QUERY_WORDS = 5
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
POPULAR_LIMIT = 10
CREATOR_LIMIT = 10
TRENDING_LIMIT = 6
RECENT_LIMIT = 10
TRENDING_DAYS = 7
POPULAR_DAYS = 30
# A term only trends once this many different people searched it, so one
# person's typo or slur never reaches everyone else's screen.
TRENDING_MIN_USERS = 2
# The same person re-running a search (typing, paging, refresh) counts once.
RECORD_DEDUPE_MINUTES = 10


def normalize_query(text):
	return ' '.join(text.lower().split())[:MAX_QUERY_LENGTH]


def _all_words(words, *fields):
	"""Every word must appear in at least one of the fields."""
	condition = Q()
	for word in words:
		any_field = Q()
		for field in fields:
			any_field |= Q(**{f'{field}__icontains': word})
		condition &= any_field
	return condition


def _title_rank(field, query):
	return Case(
		When(**{f'{field}__istartswith': query}, then=Value(3)),
		When(**{f'{field}__icontains': query}, then=Value(2)),
		default=Value(1),
		output_field=IntegerField(),
	)


def _course_cards(request, courses):
	enrolled = Enrollment.objects.filter(student=request.user, course_id=OuterRef('pk'), status__in=LIVE_STATUSES)
	courses =with_bootcamp_data(courses).annotate(is_enrolled=Exists(enrolled))
	return HomeCourseSerializer(courses, many=True, context={'request': request}).data


def _published_courses():
	return Course.objects.filter(is_published=True).select_related(
		'instructor', 'subject', 'grade', 'skill_category', 'premium_category',
	).with_review_stats()


def _recent_students(fk, since):
	return Coalesce(Subquery(
		Enrollment.objects.filter(**{fk: OuterRef('pk')}, status__in=LIVE_STATUSES, enrolled_at__gte=since)
		.order_by().values(fk).annotate(n=Count('student_id', distinct=True)).values('n')
	), 0)


def trending_searches(now):
	since = now - timedelta(days=TRENDING_DAYS)
	rows = SearchQuery.objects.filter(created_at__gte=since, results_count__gt=0).values('normalized').annotate(
		users=Count('user', distinct=True), searches=Count('pk'), last=Max('created_at'),
	).filter(users__gte=TRENDING_MIN_USERS).order_by('-users', '-searches', '-last')[:TRENDING_LIMIT]
	labels = []
	for row in rows:
		# Show the spelling people used most recently, not the lower-cased key.
		labels.append(SearchQuery.objects.filter(normalized=row['normalized'], results_count__gt=0)
			.order_by('-created_at', '-pk').values_list('query', flat=True).first().strip())
	if len(labels) < TRENDING_LIMIT:
		# Not enough search history yet: fill with the real topics that have
		# the most published courses, never with made-up terms.
		taken = {normalize_query(label) for label in labels}
		topics = LearningInterest.objects.filter(is_active=True).annotate(
			published=Count('courses', filter=Q(courses__is_published=True)),
		).filter(published__gt=0).order_by('-published', 'display_order', 'pk').values_list('name', flat=True)
		for name in topics:
			if len(labels) >= TRENDING_LIMIT:
				break
			if normalize_query(name) not in taken:
				labels.append(name)
				taken.add(normalize_query(name))
	return labels


def recent_searches(user):
	"""This user's last distinct searches, newest first, in their own spelling."""
	recent, seen = [], set()
	# Repeats are spaced at least RECORD_DEDUPE_MINUTES apart, so a bounded
	# scan of the newest rows is enough to find RECENT_LIMIT distinct ones.
	for query, normalized in SearchQuery.objects.filter(user=user).order_by('-created_at', '-pk').values_list(
		'query', 'normalized',
	)[:RECENT_LIMIT * 20]:
		if normalized not in seen:
			seen.add(normalized)
			recent.append(query)
			if len(recent) == RECENT_LIMIT:
				break
	return recent


class RecentSearchesAPIView(APIView):
	"""The signed-in user's own search history: list, remove one, or clear."""

	authentication_classes = [JWTAuthentication, SessionAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		return Response({'recent_searches': recent_searches(request.user)})

	def delete(self, request):
		# ?q= removes every spelling of that one search; no q clears them all.
		query = request.query_params.get('q')
		rows = SearchQuery.objects.filter(user=request.user)
		if query is not None:
			if not query.strip():
				raise ValidationError({'q': 'Give the search to remove, or leave q out to clear all.'})
			rows = rows.filter(normalized=normalize_query(query))
		rows.delete()
		return Response({'recent_searches': recent_searches(request.user)})


class SearchDiscoverAPIView(APIView):
	"""What the Search screen shows before anything is typed."""

	authentication_classes = [JWTAuthentication, SessionAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request):
		now = timezone.now()
		since = now - timedelta(days=POPULAR_DAYS)
		popular = _published_courses().annotate(
			recent_students=_recent_students('course_id', since),
		).order_by(
			'-recent_students', F('average_rating').desc(nulls_last=True), '-review_count', '-created_at', 'pk',
		)[:POPULAR_LIMIT]
		creators = _public_instructors().annotate(
			recent_students=_recent_students('course__instructor_id', since),
		).order_by(
			'-recent_students', F('average_rating').desc(nulls_last=True), '-review_count', '-total_students', 'pk',
		)[:CREATOR_LIMIT]
		return Response({
			'recent_searches': recent_searches(request.user),
			'trending_searches': trending_searches(now),
			'popular_courses': _course_cards(request, popular),
			'trending_creators': PublicInstructorSerializer(creators, many=True, context={'request': request}).data,
		})


class SearchAPIView(APIView):
	"""Results for a typed query, grouped as courses, creators and Shorts."""

	authentication_classes = [JWTAuthentication, SessionAuthentication]
	permission_classes = [IsAuthenticated]

	@staticmethod
	def _int_param(params, name, default, low, high):
		raw = params.get(name)
		if raw in (None, ''):
			return default
		try:
			value = int(raw)
		except (TypeError, ValueError):
			value = None
		if value is None or not low <= value <= high:
			raise ValidationError({name: f'Must be a whole number from {low} to {high}.'})
		return value

	def get(self, request):
		params = request.query_params
		query = ' '.join(params.get('q', '').split())
		if not query:
			raise ValidationError({'q': 'Enter something to search for.'})
		if len(query) > MAX_QUERY_LENGTH:
			raise ValidationError({'q': f'Keep searches under {MAX_QUERY_LENGTH} characters.'})
		search_type = params.get('type', 'all')
		if search_type not in SEARCH_TYPES:
			raise ValidationError({'type': f'Must be one of: {", ".join(SEARCH_TYPES)}.'})
		limit = self._int_param(params, 'limit', DEFAULT_LIMIT, 1, MAX_LIMIT)
		offset = self._int_param(params, 'offset', 0, 0, 10_000)
		words = query.split()[:MAX_QUERY_WORDS]
		page = slice(offset, offset + limit)

		body = {'query': query, 'type': search_type, 'counts': {}}
		if search_type in ('all', 'courses'):
			courses = _published_courses().filter(_all_words(
				words, 'title', 'description', 'skill_category__name', 'premium_category__name',
				'subject__name', 'instructor__name',
			)).annotate(rank=_title_rank('title', query)).order_by(
				'-rank', F('average_rating').desc(nulls_last=True), '-review_count', '-created_at', 'pk',
			)
			body['counts']['courses'] = courses.count()
			body['courses'] = _course_cards(request, courses[page])
		if search_type in ('all', 'creators'):
			creators = _public_instructors().filter(_all_words(
				words, 'name', 'instructor_profile__qualification', 'instructor_profile__subject_expertise',
			)).annotate(rank=_title_rank('name', query)).order_by(
				'-rank', F('average_rating').desc(nulls_last=True), '-review_count', '-total_students', 'pk',
			)
			body['counts']['creators'] = creators.count()
			body['creators'] = PublicInstructorSerializer(creators[page], many=True, context={'request': request}).data
		if search_type in ('all', 'shorts'):
			shorts = _shorts_with_saved_state(request.user).filter(is_published=True).filter(_all_words(
				words, 'title', 'caption', 'instructor__name', 'topic__name',
			)).order_by('-created_at', '-id')
			body['counts']['shorts'] = shorts.count()
			body['shorts'] = ShortSerializer(shorts[page], many=True, context={'request': request}).data

		if offset == 0:
			_record(request.user, query, sum(body['counts'].values()))
		return Response(body)


def _record(user, query, results_count):
	normalized = normalize_query(query)
	recent = timezone.now() - timedelta(minutes=RECORD_DEDUPE_MINUTES)
	if SearchQuery.objects.filter(user=user, normalized=normalized, created_at__gte=recent).exists():
		return
	SearchQuery.objects.create(user=user, query=query, normalized=normalized, results_count=results_count)
