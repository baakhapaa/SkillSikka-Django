import io
import shutil
import tempfile
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from .models import (
	District, Event, EventRegistration, InstructorProfile, Municipality,
	Province, Role, StudentProfile, User,
)

MEDIA_ROOT = tempfile.mkdtemp()

KATHMANDU = (27.7172, 85.3240)
LALITPUR = (27.6588, 85.3247)   # ~6.5 km from Kathmandu
POKHARA = (28.2096, 83.9856)    # ~140 km away


def png():
	buffer = io.BytesIO()
	Image.new('RGB', (16, 9), 'navy').save(buffer, format='PNG')
	return SimpleUploadedFile('cover.png', buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class EventApiTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

	def setUp(self):
		self.client = APIClient()
		self.province, _ = Province.objects.get_or_create(name='Event Province')
		self.district, _ = District.objects.get_or_create(name='Event District', province=self.province)
		self.other_district, _ = District.objects.get_or_create(name='Event Other District', province=self.province)
		self.municipality, _ = Municipality.objects.get_or_create(name='Event Municipality', district=self.district)

		self.student = User.objects.create_user(
			email='event-student@example.com', password='A-strong-password-123',
			name='Student', role=Role.objects.get(name='student'),
		)
		StudentProfile.objects.create(user=self.student, district=self.district, municipality=self.municipality)
		self.host = User.objects.create_user(
			email='event-host@example.com', password='A-strong-password-123',
			name='Dr. Host', role=Role.objects.get(name='instructor'),
		)
		InstructorProfile.objects.create(user=self.host)
		self.admin = User.objects.create_user(
			email='event-admin@example.com', password='A-strong-password-123',
			name='Admin', role=Role.objects.get_or_create(name='super_admin')[0],
		)
		self.now = timezone.now()

	def make_event(self, title='Event', coords=None, published=True, days=3, **extra):
		fields = dict(
			title=title, host=self.host, host_role='Maths Dept Head',
			start_at=self.now + timedelta(days=days), end_at=self.now + timedelta(days=days, hours=4),
			district=self.district, province=self.province, is_published=published,
		)
		if coords:
			fields['latitude'], fields['longitude'] = coords
		fields.update(extra)
		return Event.objects.create(**fields)

	def as_user(self, user):
		self.client.force_authenticate(user)

	# ---------- list / detail ----------

	def test_list_hides_drafts_and_past_events_and_is_paginated(self):
		self.make_event('Upcoming')
		self.make_event('Draft', published=False)
		self.make_event('Past', days=-3)
		self.as_user(self.student)

		data = self.client.get('/api/v1/events/').json()
		self.assertEqual(data['count'], 1)
		self.assertEqual([e['title'] for e in data['results']], ['Upcoming'])
		self.assertIn('next', data)

		past = self.client.get('/api/v1/events/?upcoming=false').json()
		self.assertEqual(past['count'], 2)

	def test_event_shape(self):
		event = self.make_event('Masterclass', coords=KATHMANDU, highlights=['Limits', 'Derivatives'], capacity=10)
		self.as_user(self.student)

		data = self.client.get(f'/api/v1/events/{event.pk}/?lat={LALITPUR[0]}&lng={LALITPUR[1]}').json()
		self.assertEqual(data['host']['name'], 'Dr. Host')
		self.assertEqual(data['host']['role'], 'Maths Dept Head')
		self.assertEqual(data['highlights'], ['Limits', 'Derivatives'])
		self.assertEqual(data['district_id'], self.district.pk)
		self.assertAlmostEqual(data['distance_km'], 6.5, delta=0.5)
		self.assertEqual(data['my_status'], 'none')
		self.assertEqual(data['spots_left'], 10)
		self.assertIsNone(data['rating'])
		self.assertIsNone(data['cover_image_url'])
		self.assertTrue(data['start_at'].endswith('Z'))

	def test_draft_detail_is_404(self):
		draft = self.make_event(published=False)
		self.as_user(self.student)
		self.assertEqual(self.client.get(f'/api/v1/events/{draft.pk}/').status_code, 404)

	def test_requires_login(self):
		self.assertEqual(self.client.get('/api/v1/events/').status_code, 401)

	# ---------- near you ----------

	def test_near_by_gps_orders_by_distance_and_applies_radius(self):
		self.make_event('Lalitpur', coords=LALITPUR)
		self.make_event('Kathmandu', coords=KATHMANDU)
		self.make_event('Pokhara', coords=POKHARA)
		self.as_user(self.student)

		data = self.client.get(f'/api/v1/events/?near=true&lat={KATHMANDU[0]}&lng={KATHMANDU[1]}&radius_km=25').json()
		self.assertEqual(data['near_scope'], 'gps')
		self.assertEqual([e['title'] for e in data['results']], ['Kathmandu', 'Lalitpur'])

	def test_near_without_gps_falls_back_to_profile_area(self):
		self.make_event('Same municipality', municipality=self.municipality)
		self.make_event('Same district only')
		self.make_event('Elsewhere', district=self.other_district)
		self.as_user(self.student)

		data = self.client.get('/api/v1/events/?near=true').json()
		self.assertEqual(data['near_scope'], 'municipality')
		self.assertEqual([e['title'] for e in data['results']], ['Same municipality'])

		Event.objects.filter(municipality=self.municipality).delete()
		data = self.client.get('/api/v1/events/?near=true').json()
		self.assertEqual(data['near_scope'], 'district')
		self.assertEqual([e['title'] for e in data['results']], ['Same district only'])

	def test_near_with_no_match_returns_everything(self):
		self.make_event('Elsewhere', district=self.other_district)
		self.as_user(self.host)  # instructor profile has no area
		data = self.client.get(f'/api/v1/events/?near=true&lat={POKHARA[0]}&lng={POKHARA[1]}').json()
		self.assertEqual(data['near_scope'], 'all')
		self.assertEqual(data['count'], 1)

	def test_bad_coordinates_are_rejected(self):
		self.as_user(self.student)
		self.assertEqual(self.client.get('/api/v1/events/?lat=200&lng=85').status_code, 400)
		self.assertEqual(self.client.get('/api/v1/events/?lat=27').status_code, 400)

	# ---------- registration ----------

	def test_register_waitlist_and_promotion(self):
		event = self.make_event(capacity=1)
		other = User.objects.create_user(
			email='event-other@example.com', password='A-strong-password-123',
			name='Other', role=Role.objects.get(name='student'),
		)

		self.as_user(self.student)
		response = self.client.post(f'/api/v1/events/{event.pk}/register/')
		self.assertEqual(response.status_code, 201)
		self.assertEqual(response.json()['my_status'], 'registered')
		self.assertEqual(response.json()['attendee_count'], 1)
		# Registering again is harmless.
		self.assertEqual(self.client.post(f'/api/v1/events/{event.pk}/register/').status_code, 200)

		self.as_user(other)
		self.assertEqual(self.client.post(f'/api/v1/events/{event.pk}/register/').json()['my_status'], 'waitlisted')

		self.as_user(self.student)
		self.assertEqual(self.client.delete(f'/api/v1/events/{event.pk}/register/').json()['my_status'], 'none')
		self.assertEqual(EventRegistration.objects.get(user=other).status, 'registered')

	def test_cannot_register_for_ended_event(self):
		event = self.make_event(days=-2)
		self.as_user(self.student)
		self.assertEqual(self.client.post(f'/api/v1/events/{event.pk}/register/').status_code, 400)

	# ---------- bookmarks ----------

	def test_save_and_saved_list(self):
		event = self.make_event('Saved one')
		self.make_event('Not saved')
		self.as_user(self.student)

		self.assertTrue(self.client.post(f'/api/v1/events/{event.pk}/save/').json()['is_saved'])
		saved = self.client.get('/api/v1/events/saved/').json()
		self.assertEqual([e['title'] for e in saved['results']], ['Saved one'])
		self.assertTrue(saved['results'][0]['is_saved'])

		self.assertFalse(self.client.delete(f'/api/v1/events/{event.pk}/save/').json()['is_saved'])
		self.assertEqual(self.client.get('/api/v1/events/saved/').json()['count'], 0)

	# ---------- admin ----------

	def admin_payload(self, **overrides):
		payload = {
			'title': 'New event', 'description': 'About it',
			'start_at': (self.now + timedelta(days=5)).isoformat(),
			'end_at': (self.now + timedelta(days=5, hours=2)).isoformat(),
			'format': 'in_person', 'venue_name': 'Hall A', 'city': 'Kathmandu',
			'district_id': self.district.pk, 'host_id': self.host.pk,
			'latitude': '27.717200', 'longitude': '85.324000', 'is_published': True,
		}
		payload.update(overrides)
		return payload

	def test_admin_creates_event_with_cover(self):
		self.as_user(self.admin)
		response = self.client.post('/api/v1/admin/events/', dict(self.admin_payload(), cover_image=png()), format='multipart')
		self.assertEqual(response.status_code, 201, response.content)
		event = Event.objects.get(title='New event')
		self.assertEqual(event.province, self.province)
		self.assertTrue(event.cover_image.name.startswith('events/'))

		self.as_user(self.student)
		data = self.client.get(f'/api/v1/events/{event.pk}/').json()
		self.assertTrue(data['cover_image_url'].startswith('http://testserver/media/events/'))

	def test_admin_validation(self):
		self.as_user(self.admin)
		cases = [
			({'end_at': (self.now + timedelta(days=4)).isoformat()}, 'end_at'),
			({'longitude': None}, 'latitude'),
			({'district_id': None}, 'district_id'),
			({'host_id': self.student.pk}, 'host_id'),
		]
		for overrides, field in cases:
			with self.subTest(field=field):
				response = self.client.post('/api/v1/admin/events/', self.admin_payload(**overrides), format='json')
				self.assertEqual(response.status_code, 400)
				self.assertIn(field, response.json())

	def test_online_event_needs_no_district(self):
		self.as_user(self.admin)
		response = self.client.post('/api/v1/admin/events/', self.admin_payload(
			format='online', district_id=None, latitude=None, longitude=None,
		), format='json')
		self.assertEqual(response.status_code, 201, response.content)

	def test_admin_routes_are_super_admin_only(self):
		self.as_user(self.student)
		self.assertEqual(self.client.get('/api/v1/admin/events/').status_code, 403)
		self.assertEqual(self.client.post('/api/v1/admin/events/', self.admin_payload(), format='json').status_code, 403)

	def test_admin_sees_registrations(self):
		event = self.make_event()
		EventRegistration.objects.create(event=event, user=self.student, status='registered')
		self.as_user(self.admin)
		data = self.client.get(f'/api/v1/admin/events/{event.pk}/registrations/').json()
		self.assertEqual(data['results'][0]['email'], self.student.email)
