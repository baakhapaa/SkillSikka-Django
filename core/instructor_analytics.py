"""Studio analytics for one course, and the watch-time write that feeds it.

Contract: docs/instructor-analytics-integration.md. Every figure is derived from
rows already stored (enrollments, payments, lesson completions, watch time);
anything never recorded is returned as null, never as a guessed 0.
"""
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_views import _is_student, _student_lesson_access
from .authentication import EmailVerifiedJWTAuthentication as JWTAuthentication
from .course_access import CourseAPIError, is_course_manager
from .models import Course, Lesson, LessonProgress, LessonWatchTime, Payment


PERIOD_DAYS = {'7d': 7, '30d': 30, '90d': 90, 'all': None}
SOURCE_KEYS = ('direct', 'organic', 'social', 'unknown')
LIVE_STATUSES = ('active', 'completed')
# The player reports every few seconds; one report never covers more than this.
MAX_REPORT_SECONDS = 120
# Slack on top of wall-clock time between reports, for network jitter.
REPORT_GRACE_SECONDS = 5


def _today():
	return timezone.localdate()


def _delta_percent(current, previous):
	if previous is None or not previous:
		return None
	return round(float((current - previous) / previous * 100), 1)


def _in(day, window):
	return window is not None and window[0] <= day <= window[1]


def _live_enrollments(course):
	"""Active/completed enrollments with the date each became active.

	There is no activation timestamp column. A paid enrollment turns active when
	its payment succeeds and a free one is created active, so the first
	successful payment's time, else `enrolled_at`, is when it entered `active`.
	"""
	paid_at = Payment.objects.filter(enrollment=OuterRef('pk'), status='successful').annotate(
		at=Coalesce('verified_at', 'created_at'),
	).order_by('at').values('at')[:1]
	rows = course.enrollments.filter(status__in=LIVE_STATUSES).annotate(
		activated_at=Coalesce(Subquery(paid_at), 'enrolled_at'),
	).values('student_id', 'activated_at', 'source')
	return [{**row, 'activated_on': timezone.localdate(row['activated_at'])} for row in rows]


def _revenue(course, window):
	if window is None:
		return None
	total = Payment.objects.filter(course=course, status='successful').annotate(
		paid_at=Coalesce('verified_at', 'created_at'),
	).filter(paid_at__date__range=window).aggregate(total=Sum('amount'))['total']
	return total or Decimal('0')


def _watch_seconds(course, window):
	if window is None:
		return None
	return LessonWatchTime.objects.filter(lesson__course=course, date__range=window).aggregate(
		total=Sum('watched_seconds'),
	)['total'] or 0


def _avg_completion(enrollments, completions, lesson_count, as_of):
	"""Mean completed/total lessons over enrollments live by `as_of`, 0-100."""
	if as_of is None or not lesson_count:
		return None
	ratios = []
	for enrollment in enrollments:
		if enrollment['activated_on'] > as_of:
			continue
		done = sum(
			1 for completed_on in completions.get(enrollment['student_id'], {}).values()
			if completed_on is None or completed_on <= as_of
		)
		ratios.append(min(done, lesson_count) / lesson_count)
	if not ratios:
		return None
	return round(sum(ratios) / len(ratios) * 100, 1)


def course_analytics(course, period, today):
	days = PERIOD_DAYS[period]
	if days is None:
		window = (min(timezone.localdate(course.created_at), today), today)
		previous = None
	else:
		window = (today - timedelta(days=days - 1), today)
		previous_end = window[0] - timedelta(days=1)
		previous = (previous_end - timedelta(days=days - 1), previous_end)

	enrollments = _live_enrollments(course)
	students = {row['student_id'] for row in enrollments}
	new_now = [row for row in enrollments if _in(row['activated_on'], window)]
	new_before = sum(1 for row in enrollments if _in(row['activated_on'], previous)) if previous else None

	revenue_now = _revenue(course, window)
	revenue_before = _revenue(course, previous)

	if LessonWatchTime.objects.filter(lesson__course=course).exists():
		watch_now = _watch_seconds(course, window)
		watch_delta = _delta_percent(watch_now, _watch_seconds(course, previous))
	else:
		# Never recorded for this course: null, so the app keeps its dash.
		watch_now = watch_delta = None

	lessons = list(Lesson.objects.filter(course=course).order_by('order', 'title', 'pk').values('pk', 'section'))
	completions = {}
	for student_id, lesson_id, completed_at in LessonProgress.objects.filter(
		lesson__course=course, is_completed=True,
	).values_list('student_id', 'lesson_id', 'completed_at'):
		if student_id in students:
			completions.setdefault(student_id, {})[lesson_id] = (
				timezone.localdate(completed_at) if completed_at else None
			)
	completion_now = _avg_completion(enrollments, completions, len(lessons), window[1])
	completion_before = _avg_completion(enrollments, completions, len(lessons), previous[1] if previous else None)

	# First-seen section order, the same order GET /lessons/?course= returns.
	sections = {}
	for lesson in lessons:
		sections.setdefault((lesson['section'] or '').strip() or 'Lessons', set()).add(lesson['pk'])
	retention = []
	for name, lesson_ids in sections.items():
		finished = sum(1 for row in enrollments if lesson_ids <= completions.get(row['student_id'], {}).keys())
		retention.append({
			'section': name,
			'lesson_count': len(lesson_ids),
			'completion_percent': round(finished / len(enrollments) * 100, 1) if enrollments else None,
		})

	per_day = Counter(row['activated_on'] for row in new_now)
	span = (window[1] - window[0]).days + 1
	enrollments_by_day = [
		{'date': (window[0] + timedelta(days=i)).isoformat(), 'count': per_day.get(window[0] + timedelta(days=i), 0)}
		for i in range(span)
	]

	# Empty until some enrollment carries a real source; old rows are all
	# `unknown` and are never split across the other buckets.
	sources = []
	if course.enrollments.exclude(source='unknown').exists():
		by_source = Counter(row['source'] for row in new_now)
		sources = [{
			'key': key,
			'share_percent': round(by_source[key] / len(new_now) * 100, 1) if new_now else None,
			# The app sends no visits, so there is nothing to convert from.
			'conversion_percent': None,
		} for key in SOURCE_KEYS]

	return {
		'period': period,
		'period_start': window[0].isoformat(),
		'period_end': window[1].isoformat(),
		'previous_period_start': previous[0].isoformat() if previous else None,
		'previous_period_end': previous[1].isoformat() if previous else None,
		'revenue': {
			'amount': str(revenue_now.quantize(Decimal('0.01'))),
			'currency': 'NPR',
			'delta_percent': _delta_percent(revenue_now, revenue_before),
		},
		'students': {
			'enrolled_now': len(enrollments),
			'new_in_period': len(new_now),
			'delta_percent': _delta_percent(len(new_now), new_before),
		},
		'watch_time_seconds': watch_now,
		'watch_time_delta_percent': watch_delta,
		'avg_completion_percent': completion_now,
		'avg_completion_delta_points': (
			round(completion_now - completion_before, 1)
			if completion_now is not None and completion_before is not None else None
		),
		'enrollments_by_day': enrollments_by_day,
		'retention': retention,
		'sources': sources,
	}


class CourseInstructorAnalyticsAPIView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def get(self, request, course_id):
		course = Course.objects.filter(pk=course_id).first()
		if course is None:
			raise CourseAPIError('COURSE_NOT_FOUND', 'Course not found.', 404)
		if not is_course_manager(request.user, course):
			raise CourseAPIError('NOT_COURSE_OWNER', 'Only the course owner or an administrator can view its analytics.', 403)
		period = request.query_params.get('period', '30d')
		if period not in PERIOD_DAYS:
			raise CourseAPIError('INVALID_PERIOD', 'period must be one of: 7d, 30d, 90d, all.', 400)
		return Response(course_analytics(course, period, _today()))


class LessonWatchProgressSerializer(serializers.Serializer):
	watched_seconds = serializers.IntegerField(min_value=1, max_value=MAX_REPORT_SECONDS)
	position_seconds = serializers.IntegerField(min_value=0, required=False)


class LessonWatchProgressAPIView(APIView):
	"""The player's periodic report while a lesson is open."""

	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]

	def post(self, request, lesson_id):
		lesson = Lesson.objects.filter(pk=lesson_id).select_related('course', 'topic__chapter').first()
		if lesson is None:
			return Response({'detail': 'Lesson not found.'}, status=status.HTTP_404_NOT_FOUND)
		if not _is_student(request.user):
			raise PermissionDenied('Only students record watch time.')
		_, denied = _student_lesson_access(request.user, lesson)
		if denied is not None:
			return denied
		serializer = LessonWatchProgressSerializer(data=request.data)
		serializer.is_valid(raise_exception=True)
		data = serializer.validated_data

		now = timezone.now()
		with transaction.atomic():
			# The client's number is a claim, not the truth: credit at most the
			# wall-clock time since this student's previous report on any
			# lesson, so replays or two open players cannot inflate the total.
			last = LessonWatchTime.objects.select_for_update().filter(student=request.user).order_by('-updated_at').first()
			credited = data['watched_seconds']
			if last is not None:
				elapsed = int((now - last.updated_at).total_seconds())
				credited = max(0, min(credited, elapsed + REPORT_GRACE_SECONDS))
			row, _ = LessonWatchTime.objects.select_for_update().get_or_create(
				student=request.user, lesson=lesson, date=timezone.localdate(now),
			)
			row.watched_seconds = F('watched_seconds') + credited
			if 'position_seconds' in data:
				row.position_seconds = data['position_seconds']
			row.save()
			row.refresh_from_db()

		total = LessonWatchTime.objects.filter(student=request.user, lesson=lesson).aggregate(
			total=Sum('watched_seconds'),
		)['total']
		return Response({
			'lesson_id': lesson.pk,
			'credited_seconds': credited,
			'total_watched_seconds': total,
			'position_seconds': row.position_seconds,
		})
