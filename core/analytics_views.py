import csv
import datetime
from decimal import Decimal

from django.db.models import Avg, Count, Max, Q, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.utils import timezone

from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework_simplejwt.authentication import JWTAuthentication

from .api_views import _is_admin, _is_instructor
from .models import (
	Challenge,
	ChallengeParticipant,
	Course,
	Enrollment,
	Lesson,
	LessonProgress,
	PointTransaction,
	Question,
	Quiz,
	QuizAttempt,
	StudentAnswer,
	User,
)


# =========================================================
# Small helpers
# =========================================================

SCORE_BUCKETS = [
	('0-19', 0, 20),
	('20-39', 20, 40),
	('40-59', 40, 60),
	('60-79', 60, 80),
	('80-100', 80, 101),
]


def _num(value, digits=2):
	if value is None:
		return None

	return round(float(value), digits)


def _percent(part, whole):
	if not whole:
		return None

	return round(part * 100 / whole, 2)


def _int_param(request, name, default, minimum, maximum):
	try:
		value = int(request.query_params.get(name, default))
	except (TypeError, ValueError):
		value = default

	return max(minimum, min(value, maximum))


def _require_teacher(user):
	if not (_is_admin(user) or _is_instructor(user)):
		raise PermissionDenied(
			'Only instructors or administrators can view analytics.'
		)


def _scoped_courses(request):
	user = request.user
	_require_teacher(user)

	courses = Course.objects.all()

	if _is_admin(user):
		instructor_id = request.query_params.get('instructor')

		if instructor_id and instructor_id.isdigit():
			courses = courses.filter(
				instructor_id=int(instructor_id)
			)

	else:
		courses = courses.filter(instructor=user)

	return courses


def _get_course_for_analytics(request, course_id):
	_require_teacher(request.user)

	course = Course.objects.select_related(
		'instructor',
	).filter(
		pk=course_id
	).first()

	if course is None:
		raise NotFound('Course not found.')

	if (
		not _is_admin(request.user)
		and course.instructor_id != request.user.id
	):
		raise PermissionDenied(
			'You can only view analytics for your own courses.'
		)

	return course


# =========================================================
# Time ranges
# =========================================================

def _parse_date(value, name):
	try:
		return datetime.date.fromisoformat(value)
	except (TypeError, ValueError):
		raise ValidationError({name: 'Use the format YYYY-MM-DD.'})


def _day_start(day):
	return timezone.make_aware(
		datetime.datetime.combine(day, datetime.time.min)
	)


def _get_range(request, default_days=None):
	params = request.query_params

	from_raw = params.get('from')
	to_raw = params.get('to')
	days_raw = params.get('days')

	if from_raw or to_raw:
		if not from_raw:
			raise ValidationError({
				'from': 'Provide "from" when using "to".'
			})

		from_date = _parse_date(from_raw, 'from')
		to_date = _parse_date(to_raw, 'to') if to_raw else timezone.localdate()

	elif days_raw or default_days:
		try:
			days = int(days_raw) if days_raw else int(default_days)
		except (TypeError, ValueError):
			raise ValidationError({'days': 'Use a whole number of days.'})

		days = max(1, min(days, 3650))
		to_date = timezone.localdate()
		from_date = to_date - datetime.timedelta(days=days - 1)

	else:
		return None

	if from_date > to_date:
		raise ValidationError({
			'detail': '"from" must not be after "to".'
		})

	return {
		'from': from_date,
		'to': to_date,
		'start': _day_start(from_date),
		'end': _day_start(to_date + datetime.timedelta(days=1)),
	}


def _period_output(period):
	if period is None:
		return None

	return {
		'from': period['from'].isoformat(),
		'to': period['to'].isoformat(),
	}


def _in_range(queryset, field, period):
	if period is None:
		return queryset

	return queryset.filter(**{
		f'{field}__gte': period['start'],
		f'{field}__lt': period['end'],
	})


# =========================================================
# CSV helpers
# =========================================================

def _csv_cell(value):
	if value is None:
		return ''

	if isinstance(value, bool):
		return 'yes' if value else 'no'

	if isinstance(value, (int, float, Decimal)):
		return str(value)

	if isinstance(value, datetime.datetime):
		if timezone.is_aware(value):
			value = timezone.localtime(value)

		return value.strftime('%Y-%m-%d %H:%M:%S')

	text = str(value)

	if text[:1] in ('=', '+', '-', '@', '\t', '\r'):
		return "'" + text

	return text


def _csv_response(filename, header, rows):
	response = HttpResponse(content_type='text/csv; charset=utf-8')
	response['Content-Disposition'] = f'attachment; filename="{filename}"'
	response.write('\ufeff')

	writer = csv.writer(response)
	writer.writerow(header)

	for row in rows:
		writer.writerow([_csv_cell(value) for value in row])

	return response


class AnalyticsView(APIView):
	authentication_classes = [JWTAuthentication]
	permission_classes = [IsAuthenticated]


class CsvAnalyticsView(AnalyticsView):
	def perform_content_negotiation(self, request, force=False):
		renderer = self.get_renderers()[0]
		return (renderer, renderer.media_type)


# =========================================================
# Shared data builders
# =========================================================

def _course_student_sets(course_ids):
	students = {course_id: set() for course_id in course_ids}

	enrolled = Enrollment.objects.filter(
		course_id__in=course_ids,
		status__in=['active', 'completed'],
	).values_list('course_id', 'student_id')

	for course_id, student_id in enrolled:
		students[course_id].add(student_id)

	with_progress = LessonProgress.objects.filter(
		lesson__course_id__in=course_ids,
		is_completed=True,
	).order_by().values_list(
		'lesson__course_id',
		'student_id',
	).distinct()

	for course_id, student_id in with_progress:
		students[course_id].add(student_id)

	return students


def _enrollment_counts(course_ids):
	counts = {}

	rows = Enrollment.objects.filter(
		course_id__in=course_ids
	).order_by().values(
		'course_id',
		'status',
	).annotate(n=Count('id'))

	for row in rows:
		counts.setdefault(row['course_id'], {})[row['status']] = row['n']

	return counts


def _enrollment_summary(status_counts):
	return {
		'active': status_counts.get('active', 0),
		'completed': status_counts.get('completed', 0),
		'pending_payment': status_counts.get('pending_payment', 0),
	}


def _last_activity(course_ids):
	last = {}

	lesson_rows = LessonProgress.objects.filter(
		lesson__course_id__in=course_ids,
		is_completed=True,
		completed_at__isnull=False,
	).order_by().values(
		'lesson__course_id',
		'student_id',
	).annotate(last=Max('completed_at'))

	for row in lesson_rows:
		key = (row['lesson__course_id'], row['student_id'])
		last[key] = row['last']

	quiz_rows = QuizAttempt.objects.filter(
		quiz__course_id__in=course_ids,
		completed_at__isnull=False,
	).order_by().values(
		'quiz__course_id',
		'student_id',
	).annotate(last=Max('completed_at'))

	for row in quiz_rows:
		key = (row['quiz__course_id'], row['student_id'])

		if key not in last or row['last'] > last[key]:
			last[key] = row['last']

	return last


def _days_since(moment, now):
	if moment is None:
		return None

	return max((now - moment).days, 0)


def _average_days_to_complete(course_ids):
	totals = {}

	rows = Enrollment.objects.filter(
		course_id__in=course_ids,
		completed_at__isnull=False,
	).values_list('course_id', 'enrolled_at', 'completed_at')

	for course_id, enrolled_at, completed_at in rows:
		seconds = (completed_at - enrolled_at).total_seconds()
		bucket = totals.setdefault(course_id, [0.0, 0])
		bucket[0] += max(seconds, 0)
		bucket[1] += 1

	return {
		course_id: round(total / count / 86400, 2)
		for course_id, (total, count) in totals.items()
		if count
	}


# =========================================================
# Course summaries
# =========================================================

def _course_summaries(courses, period, inactive_days):
	courses = list(
		courses.select_related('instructor').order_by('-created_at')
	)

	course_ids = [course.id for course in courses]

	if not course_ids:
		return []

	now = timezone.now()
	cutoff = now - datetime.timedelta(days=inactive_days)

	students = _course_student_sets(course_ids)
	enrollments = _enrollment_counts(course_ids)
	last_activity = _last_activity(course_ids)
	days_to_complete = _average_days_to_complete(course_ids)

	lesson_totals = {
		row['course_id']: row['total']
		for row in Lesson.objects.filter(
			course_id__in=course_ids
		).order_by().values('course_id').annotate(
			total=Count('id')
		)
	}

	progress = {}

	progress_rows = LessonProgress.objects.filter(
		lesson__course_id__in=course_ids,
		is_completed=True,
	).order_by().values(
		'lesson__course_id',
		'student_id',
	).annotate(
		done=Count('lesson', distinct=True)
	)

	for row in progress_rows:
		progress.setdefault(
			row['lesson__course_id'], []
		).append(row['done'])

	quiz_rows = {
		row['quiz__course_id']: row
		for row in QuizAttempt.objects.filter(
			quiz__course_id__in=course_ids,
			completed_at__isnull=False,
		).order_by().values('quiz__course_id').annotate(
			attempts=Count('id'),
			students=Count('student', distinct=True),
			average=Avg('percentage'),
			passed=Count('id', filter=Q(is_passed=True)),
		)
	}

	period_new = {}
	period_lessons = {}
	period_attempts = {}
	period_active = {course_id: set() for course_id in course_ids}

	if period is not None:
		period_new = {
			row['course_id']: row['n']
			for row in _in_range(
				Enrollment.objects.filter(
					course_id__in=course_ids,
					status__in=['active', 'completed'],
				),
				'enrolled_at',
				period,
			).order_by().values('course_id').annotate(n=Count('id'))
		}

		lesson_period = _in_range(
			LessonProgress.objects.filter(
				lesson__course_id__in=course_ids,
				is_completed=True,
			),
			'completed_at',
			period,
		)

		period_lessons = {
			row['lesson__course_id']: row['n']
			for row in lesson_period.order_by().values(
				'lesson__course_id'
			).annotate(n=Count('id'))
		}

		for course_id, student_id in lesson_period.order_by().values_list(
			'lesson__course_id',
			'student_id',
		).distinct():
			period_active[course_id].add(student_id)

		attempt_period = _in_range(
			QuizAttempt.objects.filter(
				quiz__course_id__in=course_ids,
				completed_at__isnull=False,
			),
			'completed_at',
			period,
		)

		period_attempts = {
			row['quiz__course_id']: row['n']
			for row in attempt_period.order_by().values(
				'quiz__course_id'
			).annotate(n=Count('id'))
		}

		for course_id, student_id in attempt_period.order_by().values_list(
			'quiz__course_id',
			'student_id',
		).distinct():
			period_active[course_id].add(student_id)

	results = []

	for course in courses:
		total_lessons = lesson_totals.get(course.id, 0)
		student_ids = students[course.id]
		student_count = len(student_ids)
		done_counts = progress.get(course.id, [])

		completed_students = sum(
			1 for done in done_counts
			if total_lessons and done >= total_lessons
		)

		average_progress = None

		if total_lessons and student_count:
			average_progress = round(
				sum(min(done, total_lessons) for done in done_counts)
				* 100 / (total_lessons * student_count),
				2,
			)

		inactive = 0

		for student_id in student_ids:
			last = last_activity.get((course.id, student_id))

			if last is None or last < cutoff:
				inactive += 1

		quiz = quiz_rows.get(course.id)
		attempts = quiz['attempts'] if quiz else 0
		quiz_students = quiz['students'] if quiz else 0

		period_block = None

		if period is not None:
			period_block = {
				'new_enrollments': period_new.get(course.id, 0),
				'lessons_completed': period_lessons.get(course.id, 0),
				'quiz_attempts': period_attempts.get(course.id, 0),
				'active_students': len(period_active[course.id]),
			}

		results.append({
			'course_id': course.id,
			'title': course.title,
			'course_type': course.course_type,
			'is_published': course.is_published,
			'instructor_id': course.instructor_id,
			'instructor_name': course.instructor.name,
			'students': student_count,
			'enrollments': _enrollment_summary(
				enrollments.get(course.id, {})
			),
			'total_lessons': total_lessons,
			'students_completed_course': completed_students,
			'average_progress_percent': average_progress,
			'average_days_to_complete': days_to_complete.get(course.id),
			'inactive_students': inactive,
			'quiz_attempts': attempts,
			'quiz_students': quiz_students,
			'average_attempts_per_student': (
				round(attempts / quiz_students, 2) if quiz_students else None
			),
			'average_quiz_percentage': _num(quiz['average']) if quiz else None,
			'quiz_pass_rate_percent': (
				_percent(quiz['passed'], attempts) if quiz else None
			),
			'period': period_block,
		})

	return results


# =========================================================
# Student rows
# =========================================================

def _student_rows(course, request, period):
	student_ids = _course_student_sets([course.id])[course.id]
	total_lessons = Lesson.objects.filter(course=course).count()
	now = timezone.now()

	progress = {
		row['student_id']: row
		for row in LessonProgress.objects.filter(
			lesson__course=course,
			is_completed=True,
		).order_by().values('student_id').annotate(
			done=Count('lesson', distinct=True),
			last=Max('completed_at'),
		)
	}

	quizzes = {
		row['student_id']: row
		for row in QuizAttempt.objects.filter(
			quiz__course=course,
			completed_at__isnull=False,
		).order_by().values('student_id').annotate(
			attempts=Count('id'),
			average=Avg('percentage'),
			best=Max('percentage'),
			last=Max('completed_at'),
		)
	}

	lessons_in_period = {}
	attempts_in_period = {}

	if period is not None:
		lessons_in_period = {
			row['student_id']: row['n']
			for row in _in_range(
				LessonProgress.objects.filter(
					lesson__course=course,
					is_completed=True,
				),
				'completed_at',
				period,
			).order_by().values('student_id').annotate(n=Count('id'))
		}

		attempts_in_period = {
			row['student_id']: row['n']
			for row in _in_range(
				QuizAttempt.objects.filter(
					quiz__course=course,
					completed_at__isnull=False,
				),
				'completed_at',
				period,
			).order_by().values('student_id').annotate(n=Count('id'))
		}

	points = {
		row['student_id']: row['total']
		for row in PointTransaction.objects.filter(
			question__quiz__course=course,
			student_id__in=student_ids,
		).order_by().values('student_id').annotate(total=Sum('points'))
	}

	enrollments = {
		row['student_id']: row['status']
		for row in Enrollment.objects.filter(
			course=course
		).values('student_id', 'status')
	}

	users = {
		user['id']: user
		for user in User.objects.filter(
			id__in=student_ids
		).values('id', 'name', 'email')
	}

	rows = []

	for student_id in student_ids:
		user = users.get(student_id)

		if user is None:
			continue

		lesson_row = progress.get(student_id)
		quiz_row = quizzes.get(student_id)
		done = lesson_row['done'] if lesson_row else 0

		moments = [
			value for value in (
				lesson_row['last'] if lesson_row else None,
				quiz_row['last'] if quiz_row else None,
			)
			if value is not None
		]

		last_activity = max(moments) if moments else None

		row = {
			'student_id': student_id,
			'name': user['name'],
			'email': user['email'],
			'enrollment_status': enrollments.get(student_id),
			'lessons_completed': done,
			'total_lessons': total_lessons,
			'progress_percent': _percent(done, total_lessons),
			'quiz_attempts': quiz_row['attempts'] if quiz_row else 0,
			'average_quiz_percentage': _num(quiz_row['average']) if quiz_row else None,
			'best_quiz_percentage': _num(quiz_row['best']) if quiz_row else None,
			'points_earned': points.get(student_id, 0),
			'last_activity': last_activity,
			'days_inactive': _days_since(last_activity, now),
		}

		if period is not None:
			row['lessons_completed_in_period'] = lessons_in_period.get(student_id, 0)
			row['quiz_attempts_in_period'] = attempts_in_period.get(student_id, 0)

		rows.append(row)

	search = request.query_params.get('search', '').strip().lower()

	if search:
		rows = [
			row for row in rows
			if search in (row['name'] or '').lower()
			or search in (row['email'] or '').lower()
		]

	inactive_raw = request.query_params.get('inactive_days')

	if inactive_raw:
		threshold = _int_param(request, 'inactive_days', 14, 1, 3650)

		rows = [
			row for row in rows
			if row['days_inactive'] is None
			or row['days_inactive'] >= threshold
		]

	sort = request.query_params.get('sort', 'name')

	if sort == 'progress':
		rows.sort(key=lambda row: (
			-(row['progress_percent'] or 0),
			(row['name'] or '').lower(),
		))

	elif sort == 'quiz_average':
		rows.sort(key=lambda row: (
			row['average_quiz_percentage'] is None,
			-(row['average_quiz_percentage'] or 0),
			(row['name'] or '').lower(),
		))

	elif sort == 'last_activity':
		rows.sort(key=lambda row: (
			row['last_activity'] is None,
			-(row['last_activity'].timestamp() if row['last_activity'] else 0),
		))

	else:
		rows.sort(key=lambda row: (row['name'] or '').lower())

	return rows


# =========================================================
# Timeline (chart-ready series)
# =========================================================

def _bucket_day(day, interval):
	if interval == 'week':
		return day - datetime.timedelta(days=day.weekday())

	return day


def _timeline(course_ids, period, interval):
	buckets = {}

	current = period['from']
	end = period['to']

	while current <= end:
		key = _bucket_day(current, interval)

		if key not in buckets:
			buckets[key] = {
				'enrollments': 0,
				'lessons_completed': 0,
				'quiz_attempts': 0,
				'percentage_sum': Decimal('0'),
				'active': set(),
			}

		current += datetime.timedelta(days=1)

	enrollment_rows = _in_range(
		Enrollment.objects.filter(
			course_id__in=course_ids,
			status__in=['active', 'completed'],
		),
		'enrolled_at',
		period,
	).annotate(
		day=TruncDate('enrolled_at')
	).order_by().values('day').annotate(n=Count('id'))

	for row in enrollment_rows:
		buckets[_bucket_day(row['day'], interval)]['enrollments'] += row['n']

	lesson_period = _in_range(
		LessonProgress.objects.filter(
			lesson__course_id__in=course_ids,
			is_completed=True,
		),
		'completed_at',
		period,
	).annotate(day=TruncDate('completed_at'))

	for row in lesson_period.order_by().values('day').annotate(n=Count('id')):
		buckets[_bucket_day(row['day'], interval)]['lessons_completed'] += row['n']

	for day, student_id in lesson_period.order_by().values_list(
		'day',
		'student_id',
	).distinct():
		buckets[_bucket_day(day, interval)]['active'].add(student_id)

	attempt_period = _in_range(
		QuizAttempt.objects.filter(
			quiz__course_id__in=course_ids,
			completed_at__isnull=False,
		),
		'completed_at',
		period,
	).annotate(day=TruncDate('completed_at'))

	for row in attempt_period.order_by().values('day').annotate(
		n=Count('id'),
		total=Sum('percentage'),
	):
		bucket = buckets[_bucket_day(row['day'], interval)]
		bucket['quiz_attempts'] += row['n']
		bucket['percentage_sum'] += row['total'] or Decimal('0')

	for day, student_id in attempt_period.order_by().values_list(
		'day',
		'student_id',
	).distinct():
		buckets[_bucket_day(day, interval)]['active'].add(student_id)

	series = []

	totals = {
		'enrollments': 0,
		'lessons_completed': 0,
		'quiz_attempts': 0,
	}

	for key in sorted(buckets):
		bucket = buckets[key]

		totals['enrollments'] += bucket['enrollments']
		totals['lessons_completed'] += bucket['lessons_completed']
		totals['quiz_attempts'] += bucket['quiz_attempts']

		series.append({
			'date': key.isoformat(),
			'enrollments': bucket['enrollments'],
			'lessons_completed': bucket['lessons_completed'],
			'quiz_attempts': bucket['quiz_attempts'],
			'active_students': len(bucket['active']),
			'average_quiz_percentage': (
				_num(bucket['percentage_sum'] / bucket['quiz_attempts'])
				if bucket['quiz_attempts'] else None
			),
		})

	return series, totals


def _timeline_response(request, course_ids, title=None):
	interval = request.query_params.get('interval', 'day')

	if interval not in ('day', 'week'):
		raise ValidationError({
			'interval': 'Use "day" or "week".'
		})

	period = _get_range(request, default_days=30)
	span = (period['to'] - period['from']).days + 1

	limit = 366 if interval == 'day' else 1100

	if span > limit:
		raise ValidationError({
			'detail': (
				f'The range is too long for {interval} buckets. '
				f'Use at most {limit} days.'
			)
		})

	series, totals = _timeline(course_ids, period, interval)

	payload = {
		'interval': interval,
		'period': _period_output(period),
		'totals': totals,
		'series': series,
	}

	if title is not None:
		payload['course'] = title

	return Response(payload)


# =========================================================
# Challenge rows
# =========================================================

def _challenge_rows(request, period):
	user = request.user
	_require_teacher(user)

	challenges = Challenge.objects.all()

	if _is_admin(user):
		instructor_id = request.query_params.get('instructor')

		if instructor_id and instructor_id.isdigit():
			challenges = challenges.filter(
				created_by_id=int(instructor_id)
			)

	else:
		challenges = challenges.filter(created_by=user)

	challenges = list(challenges.order_by('-created_at'))
	challenge_ids = [challenge.id for challenge in challenges]

	participants = _in_range(
		ChallengeParticipant.objects.filter(
			challenge_id__in=challenge_ids
		),
		'joined_at',
		period,
	)

	rows = {
		row['challenge_id']: row
		for row in participants.order_by().values('challenge_id').annotate(
			participants=Count('id'),
			not_submitted=Count('id', filter=Q(status='joined')),
			pending_review=Count('id', filter=Q(status='submitted')),
			approved=Count('id', filter=Q(status='approved')),
			rejected=Count('id', filter=Q(status='rejected')),
			winners=Count('id', filter=Q(is_winner=True)),
			points_awarded=Sum('points_awarded'),
		)
	}

	now = timezone.now()

	results = []

	totals = {
		'participants': 0,
		'approved': 0,
		'pending_review': 0,
		'points_awarded': 0,
	}

	for challenge in challenges:
		row = rows.get(challenge.id, {})

		count = row.get('participants', 0)
		approved = row.get('approved', 0)
		pending = row.get('pending_review', 0)
		points = row.get('points_awarded') or 0

		totals['participants'] += count
		totals['approved'] += approved
		totals['pending_review'] += pending
		totals['points_awarded'] += points

		results.append({
			'challenge_id': challenge.id,
			'title': challenge.title,
			'is_published': challenge.is_published,
			'end_at': challenge.end_at,
			'is_ended': challenge.end_at <= now,
			'points': challenge.points,
			'participants': count,
			'not_submitted': row.get('not_submitted', 0),
			'pending_review': pending,
			'approved': approved,
			'rejected': row.get('rejected', 0),
			'winners': row.get('winners', 0),
			'points_awarded': points,
			'completion_rate_percent': _percent(approved, count),
		})

	return results, totals


# =========================================================
# Views: courses
# =========================================================

class TeacherCourseAnalyticsListAPIView(AnalyticsView):
	def get(self, request):
		period = _get_range(request)
		inactive_days = _int_param(request, 'inactive_days', 14, 1, 365)

		results = _course_summaries(
			_scoped_courses(request),
			period,
			inactive_days,
		)

		return Response({
			'count': len(results),
			'period': _period_output(period),
			'inactive_days': inactive_days,
			'results': results,
		})


class TeacherCourseAnalyticsExportAPIView(CsvAnalyticsView):
	def get(self, request):
		period = _get_range(request)
		inactive_days = _int_param(request, 'inactive_days', 14, 1, 365)

		results = _course_summaries(
			_scoped_courses(request),
			period,
			inactive_days,
		)

		header = [
			'course_id', 'title', 'course_type', 'is_published',
			'instructor', 'students', 'active_enrollments',
			'completed_enrollments', 'pending_payment', 'total_lessons',
			'students_completed_course', 'average_progress_percent',
			'average_days_to_complete', 'inactive_students',
			'quiz_attempts', 'average_quiz_percentage',
			'quiz_pass_rate_percent',
		]

		if period is not None:
			header += [
				'period_new_enrollments', 'period_lessons_completed',
				'period_quiz_attempts', 'period_active_students',
			]

		rows = []

		for item in results:
			row = [
				item['course_id'], item['title'], item['course_type'],
				item['is_published'], item['instructor_name'],
				item['students'], item['enrollments']['active'],
				item['enrollments']['completed'],
				item['enrollments']['pending_payment'],
				item['total_lessons'], item['students_completed_course'],
				item['average_progress_percent'],
				item['average_days_to_complete'], item['inactive_students'],
				item['quiz_attempts'], item['average_quiz_percentage'],
				item['quiz_pass_rate_percent'],
			]

			if period is not None:
				row += [
					item['period']['new_enrollments'],
					item['period']['lessons_completed'],
					item['period']['quiz_attempts'],
					item['period']['active_students'],
				]

			rows.append(row)

		return _csv_response('course-analytics.csv', header, rows)


class TeacherCourseAnalyticsDetailAPIView(AnalyticsView):
	def get(self, request, course_id):
		course = _get_course_for_analytics(request, course_id)
		period = _get_range(request)

		student_count = len(
			_course_student_sets([course.id])[course.id]
		)

		enrollments = _enrollment_counts([course.id]).get(course.id, {})

		lessons = list(
			Lesson.objects.filter(
				course=course
			).order_by('order', 'title').values(
				'id',
				'title',
				'order',
				'content_type',
			)
		)

		completions = {
			row['lesson_id']: row['n']
			for row in LessonProgress.objects.filter(
				lesson__course=course,
				is_completed=True,
			).order_by().values('lesson_id').annotate(
				n=Count('student', distinct=True)
			)
		}

		completions_in_period = {}

		if period is not None:
			completions_in_period = {
				row['lesson_id']: row['n']
				for row in _in_range(
					LessonProgress.objects.filter(
						lesson__course=course,
						is_completed=True,
					),
					'completed_at',
					period,
				).order_by().values('lesson_id').annotate(n=Count('id'))
			}

		lesson_stats = []

		for lesson in lessons:
			item = {
				'lesson_id': lesson['id'],
				'title': lesson['title'],
				'order': lesson['order'],
				'content_type': lesson['content_type'],
				'completed_by': completions.get(lesson['id'], 0),
				'completion_percent': _percent(
					completions.get(lesson['id'], 0),
					student_count,
				),
			}

			if period is not None:
				item['completed_in_period'] = completions_in_period.get(
					lesson['id'], 0
				)

			lesson_stats.append(item)

		quizzes = list(
			Quiz.objects.filter(
				course=course
			).order_by('id').values(
				'id',
				'title',
				'is_published',
				'pass_percentage',
			)
		)

		bucket_annotations = {
			f'bucket_{index}': Count(
				'id',
				filter=Q(percentage__gte=low, percentage__lt=high),
			)
			for index, (_, low, high) in enumerate(SCORE_BUCKETS)
		}

		attempt_rows = {
			row['quiz_id']: row
			for row in QuizAttempt.objects.filter(
				quiz__course=course,
				completed_at__isnull=False,
			).order_by().values('quiz_id').annotate(
				attempts=Count('id'),
				students=Count('student', distinct=True),
				average=Avg('percentage'),
				best=Max('percentage'),
				passed=Count('id', filter=Q(is_passed=True)),
				**bucket_annotations,
			)
		}

		attempts_in_period = {}

		if period is not None:
			attempts_in_period = {
				row['quiz_id']: row['n']
				for row in _in_range(
					QuizAttempt.objects.filter(
						quiz__course=course,
						completed_at__isnull=False,
					),
					'completed_at',
					period,
				).order_by().values('quiz_id').annotate(n=Count('id'))
			}

		quiz_stats = []

		for quiz in quizzes:
			row = attempt_rows.get(quiz['id'])
			attempts = row['attempts'] if row else 0
			students_attempted = row['students'] if row else 0

			item = {
				'quiz_id': quiz['id'],
				'title': quiz['title'],
				'is_published': quiz['is_published'],
				'pass_percentage': _num(quiz['pass_percentage']),
				'attempts': attempts,
				'students_attempted': students_attempted,
				'average_attempts_per_student': (
					round(attempts / students_attempted, 2)
					if students_attempted else None
				),
				'average_percentage': _num(row['average']) if row else None,
				'best_percentage': _num(row['best']) if row else None,
				'pass_rate_percent': (
					_percent(row['passed'], attempts) if row else None
				),
				'score_distribution': [
					{
						'range': label,
						'attempts': row[f'bucket_{index}'] if row else 0,
					}
					for index, (label, _, _) in enumerate(SCORE_BUCKETS)
				],
			}

			if period is not None:
				item['attempts_in_period'] = attempts_in_period.get(
					quiz['id'], 0
				)

			quiz_stats.append(item)

		answer_rows = list(
			StudentAnswer.objects.filter(
				attempt__quiz__course=course,
				attempt__completed_at__isnull=False,
			).order_by().values('question_id').annotate(
				answered=Count('id'),
				correct=Count('id', filter=Q(is_correct=True)),
			)
		)

		question_info = {
			question['id']: question
			for question in Question.objects.filter(
				id__in=[row['question_id'] for row in answer_rows]
			).values('id', 'text', 'quiz_id')
		}

		hardest = sorted(
			answer_rows,
			key=lambda row: (
				row['correct'] / row['answered'],
				-row['answered'],
			),
		)[:5]

		hardest_questions = [
			{
				'question_id': row['question_id'],
				'quiz_id': question_info.get(row['question_id'], {}).get('quiz_id'),
				'text': question_info.get(row['question_id'], {}).get('text'),
				'answered': row['answered'],
				'correct_rate_percent': _percent(row['correct'], row['answered']),
			}
			for row in hardest
		]

		return Response({
			'course': {
				'course_id': course.id,
				'title': course.title,
				'course_type': course.course_type,
				'is_published': course.is_published,
				'instructor_id': course.instructor_id,
				'instructor_name': course.instructor.name,
			},
			'period': _period_output(period),
			'students': student_count,
			'enrollments': _enrollment_summary(enrollments),
			'lessons': lesson_stats,
			'quizzes': quiz_stats,
			'hardest_questions': hardest_questions,
		})


class TeacherCourseStudentsAPIView(AnalyticsView):
	def get(self, request, course_id):
		course = _get_course_for_analytics(request, course_id)
		period = _get_range(request)

		rows = _student_rows(course, request, period)

		limit = _int_param(request, 'limit', 50, 1, 200)
		offset = _int_param(request, 'offset', 0, 0, 1000000)

		return Response({
			'course_id': course.id,
			'title': course.title,
			'period': _period_output(period),
			'count': len(rows),
			'limit': limit,
			'offset': offset,
			'results': rows[offset:offset + limit],
		})


class TeacherCourseStudentsExportAPIView(CsvAnalyticsView):
	def get(self, request, course_id):
		course = _get_course_for_analytics(request, course_id)
		period = _get_range(request)

		rows = _student_rows(course, request, period)

		header = [
			'student_id', 'name', 'email', 'enrollment_status',
			'lessons_completed', 'total_lessons', 'progress_percent',
			'quiz_attempts', 'average_quiz_percentage',
			'best_quiz_percentage', 'points_earned', 'last_activity',
			'days_inactive',
		]

		if period is not None:
			header += ['lessons_completed_in_period', 'quiz_attempts_in_period']

		data = []

		for row in rows:
			line = [
				row['student_id'], row['name'], row['email'],
				row['enrollment_status'], row['lessons_completed'],
				row['total_lessons'], row['progress_percent'],
				row['quiz_attempts'], row['average_quiz_percentage'],
				row['best_quiz_percentage'], row['points_earned'],
				row['last_activity'], row['days_inactive'],
			]

			if period is not None:
				line += [
					row['lessons_completed_in_period'],
					row['quiz_attempts_in_period'],
				]

			data.append(line)

		return _csv_response(
			f'course-{course.id}-students.csv',
			header,
			data,
		)


class TeacherCourseTimelineAPIView(AnalyticsView):
	def get(self, request, course_id):
		course = _get_course_for_analytics(request, course_id)

		return _timeline_response(
			request,
			[course.id],
			title={'course_id': course.id, 'title': course.title},
		)


class TeacherTimelineAPIView(AnalyticsView):
	def get(self, request):
		course_ids = list(
			_scoped_courses(request).values_list('id', flat=True)
		)

		return _timeline_response(request, course_ids)


# =========================================================
# Views: challenges
# =========================================================

class TeacherChallengeAnalyticsAPIView(AnalyticsView):
	def get(self, request):
		period = _get_range(request)
		results, totals = _challenge_rows(request, period)

		return Response({
			'count': len(results),
			'period': _period_output(period),
			'totals': totals,
			'results': results,
		})


class TeacherChallengeAnalyticsExportAPIView(CsvAnalyticsView):
	def get(self, request):
		period = _get_range(request)
		results, _ = _challenge_rows(request, period)

		header = [
			'challenge_id', 'title', 'is_published', 'end_at', 'is_ended',
			'points', 'participants', 'not_submitted', 'pending_review',
			'approved', 'rejected', 'winners', 'points_awarded',
			'completion_rate_percent',
		]

		rows = [
			[
				item['challenge_id'], item['title'], item['is_published'],
				item['end_at'], item['is_ended'], item['points'],
				item['participants'], item['not_submitted'],
				item['pending_review'], item['approved'], item['rejected'],
				item['winners'], item['points_awarded'],
				item['completion_rate_percent'],
			]
			for item in results
		]

		return _csv_response('challenge-analytics.csv', header, rows)