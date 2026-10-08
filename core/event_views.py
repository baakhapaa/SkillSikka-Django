import math
from collections import defaultdict

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_views import SuperAdminRequiredMixin, _create_audit_log, _notify
from .event_serializers import EventAdminSerializer, EventSerializer
from .models import Event, EventBookmark, EventRegistration, Notification, event_image_path


DEFAULT_RADIUS_KM = 25
MAX_RADIUS_KM = 200
KM_PER_DEGREE_LAT = 111.32


class EventPagination(PageNumberPagination):
	page_size = 20
	page_size_query_param = 'page_size'
	max_page_size = 50

	def get_paginated_response(self, data, extra=None):
		response = super().get_paginated_response(data)
		if extra:
			response.data.update(extra)
		return response


def _haversine_km(lat1, lng1, lat2, lng2):
	lat1, lng1, lat2, lng2 = map(math.radians, (lat1, lng1, lat2, lng2))
	a = (
		math.sin((lat2 - lat1) / 2) ** 2
		+ math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
	)
	return 6371.0 * 2 * math.asin(math.sqrt(a))


def _float_param(params, name, low, high):
	raw = params.get(name)
	if raw in (None, ''):
		return None
	try:
		value = float(raw)
	except ValueError:
		raise ValidationError({name: 'Must be a number.'})
	if not low <= value <= high:
		raise ValidationError({name: f'Must be between {low} and {high}.'})
	return value


def _bool_param(params, name, default):
	raw = params.get(name)
	if raw in (None, ''):
		return default
	return raw.lower() in ('1', 'true', 'yes')


def _user_area(user):
	"""(municipality_id, district_id) from the user's profile, if any."""
	for attr in ('student_profile', 'instructor_profile'):
		try:
			profile = getattr(user, attr)
		except ObjectDoesNotExist:
			continue
		municipality_id = profile.municipality_id
		if municipality_id is None and profile.school_id:
			municipality_id = profile.school.municipality_id
		return municipality_id, profile.district_id
	return None, None


def _with_distance(events, lat, lng):
	for event in events:
		event.distance_km = (
			_haversine_km(lat, lng, float(event.latitude), float(event.longitude))
			if lat is not None and event.latitude is not None
			else None
		)
	return events


def _viewer_context(request, events):
	ids = [event.pk for event in events]
	registered = EventRegistration.objects.filter(event_id__in=ids, status='registered')

	counts = dict(
		registered.values('event_id').annotate(total=Count('id')).values_list('event_id', 'total')
	)
	photos = defaultdict(list)
	for registration in registered.exclude(user__profile_photo_url='').select_related('user'):
		if len(photos[registration.event_id]) < 4:
			photos[registration.event_id].append(registration.user.profile_photo_src)

	return {
		'request': request,
		'attendee_counts': counts,
		'attendee_photos': photos,
		'my_statuses': dict(
			EventRegistration.objects.filter(event_id__in=ids, user=request.user)
			.values_list('event_id', 'status')
		),
		'saved_ids': set(
			EventBookmark.objects.filter(event_id__in=ids, user=request.user)
			.values_list('event_id', flat=True)
		),
	}


def _published_events():
	return Event.objects.filter(is_published=True).select_related('host')


def _event_response(request, event, status_code=status.HTTP_200_OK):
	lat = _float_param(request.query_params, 'lat', -90, 90)
	lng = _float_param(request.query_params, 'lng', -180, 180)
	_with_distance([event], lat, lng)
	data = EventSerializer(event, context=_viewer_context(request, [event])).data
	return Response(data, status=status_code)


class EventListAPIView(APIView):
	"""
	Published events, upcoming by default, paginated.

	Query parameters: near, lat, lng, radius_km, upcoming, format, district,
	municipality, search, ordering (start_at | -start_at | distance),
	page, page_size.

	near=true picks the closest events: by GPS when lat/lng are sent, then
	falling back to the viewer's municipality, then district, then all.
	The scope used is returned as near_scope.
	"""

	permission_classes = [IsAuthenticated]
	serializer_class = EventSerializer

	def get(self, request):
		params = request.query_params
		lat = _float_param(params, 'lat', -90, 90)
		lng = _float_param(params, 'lng', -180, 180)
		if (lat is None) != (lng is None):
			raise ValidationError({'lat': 'Send lat and lng together.'})
		radius_km = _float_param(params, 'radius_km', 0.1, MAX_RADIUS_KM) or DEFAULT_RADIUS_KM

		events = _published_events()
		if _bool_param(params, 'upcoming', True):
			events = events.filter(end_at__gte=timezone.now())
		if params.get('format'):
			events = events.filter(format=params['format'])
		if params.get('district'):
			events = events.filter(district_id=params['district'])
		if params.get('municipality'):
			events = events.filter(municipality_id=params['municipality'])
		if params.get('search'):
			term = params['search'].strip()
			events = events.filter(
				Q(title__icontains=term) | Q(description__icontains=term)
				| Q(venue_name__icontains=term) | Q(city__icontains=term)
			)

		ordering = params.get('ordering', 'start_at')
		if ordering not in ('start_at', '-start_at', 'distance'):
			raise ValidationError({'ordering': 'Use start_at, -start_at or distance.'})
		if ordering == 'distance' and lat is None:
			raise ValidationError({'ordering': 'Ordering by distance needs lat and lng.'})

		near_scope = None
		if _bool_param(params, 'near', False):
			events, near_scope = self._nearest(request, events, lat, lng, radius_km)
			results = list(events)
		else:
			results = list(events.order_by('-start_at' if ordering == '-start_at' else 'start_at', 'id'))
			_with_distance(results, lat, lng)
			if ordering == 'distance':
				results.sort(key=lambda e: (e.distance_km is None, e.distance_km or 0, e.start_at))

		paginator = EventPagination()
		page = paginator.paginate_queryset(results, request, view=self)
		data = EventSerializer(page, many=True, context=_viewer_context(request, page)).data
		return paginator.get_paginated_response(data, extra={'near_scope': near_scope} if near_scope else None)

	def _nearest(self, request, events, lat, lng, radius_km):
		if lat is not None:
			lat_delta = radius_km / KM_PER_DEGREE_LAT
			lng_delta = radius_km / max(KM_PER_DEGREE_LAT * math.cos(math.radians(lat)), 0.01)
			boxed = list(events.filter(
				latitude__range=(lat - lat_delta, lat + lat_delta),
				longitude__range=(lng - lng_delta, lng + lng_delta),
			))
			nearby = [e for e in _with_distance(boxed, lat, lng) if e.distance_km <= radius_km]
			if nearby:
				nearby.sort(key=lambda e: (e.distance_km, e.start_at))
				return nearby, 'gps'

		municipality_id, district_id = _user_area(request.user)
		ordered = events.order_by('start_at', 'id')
		if municipality_id and ordered.filter(municipality_id=municipality_id).exists():
			return _with_distance(list(ordered.filter(municipality_id=municipality_id)), lat, lng), 'municipality'
		if district_id and ordered.filter(district_id=district_id).exists():
			return _with_distance(list(ordered.filter(district_id=district_id)), lat, lng), 'district'
		return _with_distance(list(ordered), lat, lng), 'all'


class EventDetailAPIView(APIView):
	serializer_class = EventSerializer

	permission_classes = [IsAuthenticated]

	def get(self, request, event_id):
		return _event_response(request, get_object_or_404(_published_events(), pk=event_id))


class EventRegistrationAPIView(APIView):
	"""POST registers (waitlisted once full); DELETE cancels."""

	permission_classes = [IsAuthenticated]
	serializer_class = EventSerializer

	def post(self, request, event_id):
		with transaction.atomic():
			event = get_object_or_404(_published_events().select_for_update(of=('self',)), pk=event_id)
			if event.end_at < timezone.now():
				raise ValidationError({'detail': 'This event has already ended.'})

			existing = EventRegistration.objects.filter(event=event, user=request.user).first()
			if existing is not None:
				return _event_response(request, event)

			registered = EventRegistration.objects.filter(event=event, status='registered').count()
			full = event.capacity is not None and registered >= event.capacity
			EventRegistration.objects.create(
				event=event, user=request.user,
				status='waitlisted' if full else 'registered',
			)
			_notify(request.user, Notification.TYPE_SYSTEM,
				'Event waitlisted' if full else 'Event registration confirmed',
				f'You are on the waitlist for "{event.title}".' if full else f'You are registered for "{event.title}".',
				'event', event.pk)

		return _event_response(request, event, status.HTTP_201_CREATED)

	def delete(self, request, event_id):
		with transaction.atomic():
			event = get_object_or_404(_published_events().select_for_update(of=('self',)), pk=event_id)
			registration = EventRegistration.objects.filter(event=event, user=request.user).first()
			if registration is not None:
				freed_seat = registration.status == 'registered'
				registration.delete()
				_notify(request.user, Notification.TYPE_SYSTEM, 'Event registration cancelled',
					f'Your registration for "{event.title}" was cancelled.', 'event', event.pk)
				if freed_seat:
					next_in_line = EventRegistration.objects.filter(event=event, status='waitlisted').first()
					if next_in_line is not None:
						next_in_line.status = 'registered'
						next_in_line.save(update_fields=['status'])
						_notify(next_in_line.user, Notification.TYPE_SYSTEM, 'Event registration confirmed',
							f'A place is now available: you are registered for "{event.title}".', 'event', event.pk)

		return _event_response(request, event)


class EventBookmarkAPIView(APIView):
	permission_classes = [IsAuthenticated]

	def post(self, request, event_id):
		event = get_object_or_404(_published_events(), pk=event_id)
		EventBookmark.objects.get_or_create(event=event, user=request.user)
		return Response({'event_id': event.pk, 'is_saved': True})

	def delete(self, request, event_id):
		EventBookmark.objects.filter(event_id=event_id, user=request.user).delete()
		return Response({'event_id': event_id, 'is_saved': False})


class SavedEventListAPIView(APIView):
	serializer_class = EventSerializer

	permission_classes = [IsAuthenticated]

	def get(self, request):
		events = list(
			_published_events()
			.filter(bookmarks__user=request.user)
			.order_by('-bookmarks__created_at', 'id')
		)
		paginator = EventPagination()
		page = paginator.paginate_queryset(events, request, view=self)
		data = EventSerializer(page, many=True, context=_viewer_context(request, page)).data
		return paginator.get_paginated_response(data)


# =========================================================
# Super admin
# =========================================================

class EventAdminBase(SuperAdminRequiredMixin, APIView):
	serializer_class = EventAdminSerializer
	permission_classes = [IsAuthenticated]
	parser_classes = [JSONParser, FormParser, MultiPartParser]

	def initial(self, request, *args, **kwargs):
		super().initial(request, *args, **kwargs)
		self.check_super_admin(request)

	def write_event(self, request, event=None):
		storage = Event._meta.get_field('cover_image').storage
		serializer = EventAdminSerializer(
			event, data=request.data, partial=event is not None, context={'request': request},
		)
		serializer.is_valid(raise_exception=True)

		extra = {}
		old_name = event.cover_image.name if event else ''
		if 'cover_image' in serializer.validated_data:
			upload = serializer.validated_data.pop('cover_image')
			extra['cover_image'] = (
				storage.save(event_image_path(event, upload.name), upload) if upload else ''
			)
		if event is None:
			extra['created_by'] = request.user

		with transaction.atomic():
			saved = serializer.save(**extra)
			_create_audit_log(request, 'update' if event else 'create', 'event', saved.pk, saved.title)
			if old_name and 'cover_image' in extra and extra['cover_image'] != old_name:
				transaction.on_commit(lambda: storage.delete(old_name), robust=True)

		return Response(
			EventAdminSerializer(saved, context={'request': request}).data,
			status=status.HTTP_200_OK if event else status.HTTP_201_CREATED,
		)


class EventAdminListAPIView(EventAdminBase):
	def get(self, request):
		events = Event.objects.select_related('host').order_by('-start_at', '-id')
		results = EventAdminSerializer(events, many=True, context={'request': request}).data
		return Response({'count': len(results), 'results': results})

	def post(self, request):
		return self.write_event(request)


class EventAdminDetailAPIView(EventAdminBase):
	def get(self, request, event_id):
		event = get_object_or_404(Event, pk=event_id)
		return Response(EventAdminSerializer(event, context={'request': request}).data)

	def patch(self, request, event_id):
		return self.write_event(request, get_object_or_404(Event, pk=event_id))

	def delete(self, request, event_id):
		event = get_object_or_404(Event, pk=event_id)
		storage = Event._meta.get_field('cover_image').storage
		cover = event.cover_image.name
		with transaction.atomic():
			_create_audit_log(request, 'delete', 'event', event.pk, event.title)
			event.delete()
			if cover:
				transaction.on_commit(lambda: storage.delete(cover), robust=True)
		return Response(status=status.HTTP_204_NO_CONTENT)


class EventAdminRegistrationListAPIView(EventAdminBase):
	def get(self, request, event_id):
		event = get_object_or_404(Event, pk=event_id)
		results = [
			{
				'user_id': registration.user_id,
				'name': registration.user.name,
				'email': registration.user.email,
				'status': registration.status,
				'registered_at': registration.created_at,
			}
			for registration in event.registrations.select_related('user')
		]
		return Response({'count': len(results), 'results': results})
