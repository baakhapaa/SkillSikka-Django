from decimal import Decimal

from rest_framework import serializers

from .advertisement_serializers import validate_banner_image
from .models import District, Event, Municipality, User


class EventHostSerializer(serializers.Serializer):
	def to_representation(self, event):
		host = event.host
		if host is None:
			return None

		request = self.context.get('request')
		photo = host.profile_photo_src
		return {
			'id': host.pk,
			'name': host.name,
			'role': event.host_role or 'Instructor',
			'avatar_url': request.build_absolute_uri(photo) if photo and request else photo,
		}


class EventSerializer(serializers.ModelSerializer):
	"""What students see. Viewer-specific fields come from the view's context."""

	cover_image_url = serializers.SerializerMethodField()
	host = serializers.SerializerMethodField()
	province_id = serializers.IntegerField(read_only=True)
	district_id = serializers.IntegerField(read_only=True)
	municipality_id = serializers.IntegerField(read_only=True)
	latitude = serializers.FloatField(read_only=True)
	longitude = serializers.FloatField(read_only=True)
	distance_km = serializers.SerializerMethodField()
	attendee_count = serializers.SerializerMethodField()
	attendee_avatars = serializers.SerializerMethodField()
	spots_left = serializers.SerializerMethodField()
	my_status = serializers.SerializerMethodField()
	is_saved = serializers.SerializerMethodField()
	rating = serializers.SerializerMethodField()

	class Meta:
		model = Event
		fields = [
			'id', 'title', 'description', 'highlights', 'cover_image_url', 'host',
			'start_at', 'end_at', 'format', 'venue_name', 'city',
			'province_id', 'district_id', 'municipality_id',
			'latitude', 'longitude', 'distance_km',
			'attendee_count', 'attendee_avatars', 'capacity', 'spots_left',
			'my_status', 'is_saved', 'rating', 'is_published',
			'created_at', 'updated_at',
		]

	def _request(self):
		return self.context.get('request')

	def get_cover_image_url(self, event):
		if not event.cover_image:
			return None
		request = self._request()
		url = event.cover_image.url
		return request.build_absolute_uri(url) if request else url

	def get_host(self, event):
		return EventHostSerializer(context=self.context).to_representation(event)

	def get_distance_km(self, event):
		distance = getattr(event, 'distance_km', None)
		return round(distance, 1) if distance is not None else None

	def get_attendee_count(self, event):
		return self.context.get('attendee_counts', {}).get(event.pk, 0)

	def get_attendee_avatars(self, event):
		request = self._request()
		urls = []
		for photo in self.context.get('attendee_photos', {}).get(event.pk, []):
			urls.append(request.build_absolute_uri(photo) if request else photo)
		return urls

	def get_spots_left(self, event):
		if event.capacity is None:
			return None
		return max(event.capacity - self.get_attendee_count(event), 0)

	def get_my_status(self, event):
		return self.context.get('my_statuses', {}).get(event.pk, 'none')

	def get_is_saved(self, event):
		return event.pk in self.context.get('saved_ids', set())

	def get_rating(self, event):
		# Event ratings are not built yet; the app hides the stars on null.
		return None


class EventAdminSerializer(serializers.ModelSerializer):
	cover_image = serializers.FileField(required=False, allow_null=True)
	host_id = serializers.PrimaryKeyRelatedField(
		queryset=User.objects.filter(role__name='instructor'),
		source='host',
		required=False,
		allow_null=True,
	)
	district_id = serializers.PrimaryKeyRelatedField(
		queryset=District.objects.select_related('province'),
		source='district',
		required=False,
		allow_null=True,
	)
	municipality_id = serializers.PrimaryKeyRelatedField(
		queryset=Municipality.objects.select_related('district'),
		source='municipality',
		required=False,
		allow_null=True,
	)
	province_id = serializers.IntegerField(read_only=True)
	latitude = serializers.DecimalField(
		max_digits=9, decimal_places=6, min_value=Decimal('-90'), max_value=Decimal('90'),
		required=False, allow_null=True,
	)
	longitude = serializers.DecimalField(
		max_digits=9, decimal_places=6, min_value=Decimal('-180'), max_value=Decimal('180'),
		required=False, allow_null=True,
	)
	highlights = serializers.ListField(
		child=serializers.CharField(max_length=200),
		required=False,
		max_length=10,
	)

	class Meta:
		model = Event
		fields = [
			'id', 'title', 'description', 'highlights', 'cover_image',
			'host_id', 'host_role', 'start_at', 'end_at', 'format',
			'venue_name', 'city', 'province_id', 'district_id', 'municipality_id',
			'latitude', 'longitude', 'capacity', 'is_published',
			'created_by', 'created_at', 'updated_at',
		]
		read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

	def validate_cover_image(self, upload):
		if upload is None:
			return None
		return validate_banner_image(upload)

	def validate_capacity(self, value):
		if value is not None and value < 1:
			raise serializers.ValidationError('Capacity must be at least 1, or empty for no limit.')
		return value

	def to_representation(self, event):
		data = super().to_representation(event)
		request = self.context.get('request')
		if event.cover_image:
			url = event.cover_image.url
			data['cover_image'] = request.build_absolute_uri(url) if request else url
		else:
			data['cover_image'] = None
		return data

	def validate(self, attrs):
		def current(name):
			if name in attrs:
				return attrs[name]
			return getattr(self.instance, name, None)

		errors = {}
		start_at, end_at = current('start_at'), current('end_at')
		if start_at and end_at and end_at < start_at:
			errors['end_at'] = 'End time must not be earlier than start time.'

		latitude, longitude = current('latitude'), current('longitude')
		if (latitude is None) != (longitude is None):
			errors['latitude'] = 'Send latitude and longitude together, or neither.'

		district, municipality = current('district'), current('municipality')
		if municipality is not None and district is None:
			district = municipality.district
			attrs['district'] = district
		if municipality is not None and municipality.district_id != district.pk:
			errors['municipality_id'] = 'Municipality does not belong to the selected district.'

		if (current('format') or 'in_person') in ('in_person', 'hybrid') and district is None:
			errors['district_id'] = 'In-person and hybrid events need a district.'

		if errors:
			raise serializers.ValidationError(errors)

		attrs['province'] = district.province if district is not None else None
		return attrs
