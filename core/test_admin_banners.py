import io
import shutil
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from .models import Advertisement, AuditLog, Role, StudentProfile, User


MEDIA_ROOT = tempfile.mkdtemp()


def png(name='banner.png', size=(1280, 720)):
    buffer = io.BytesIO()
    Image.new('RGB', size, (120, 40, 160)).save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class BannerAdminPageTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.admin = User.objects.create_user(email='banner-admin@example.com', password='A-strong-password-123',
            name='Banner Admin', role=Role.objects.get(name='super_admin'), onboarding_completed=True)
        self.client.force_login(self.admin)
        self.list_url = reverse('manage_banners')

    def add(self, expect_created=True, **overrides):
        data = {'title': 'Bags collection', 'banner_image': png(), 'description': '', 'cta_text': '',
                'cta_url': '', 'starts_at': '', 'ends_at': '', 'is_active': 'on'}
        data.update(overrides)
        before = Advertisement.objects.count()
        response = self.client.post(self.list_url, data)
        self.assertEqual(Advertisement.objects.count(), before + (1 if expect_created else 0))
        return response

    def act(self, banner, action):
        return self.client.post(reverse('banner_action', args=[banner.pk]), {'action': action})

    def app_banner_ids(self):
        student = User.objects.create_user(email=f'app{User.objects.count()}@example.com', name='Student',
            role=Role.objects.get(name='student'))
        api = APIClient()
        api.force_authenticate(student)
        return [row['id'] for row in api.get('/api/v1/advertisements/').data]

    def test_only_admins_reach_the_page(self):
        staff = User.objects.create_user(email='staff@example.com', name='Staff', role=Role.objects.get(name='school_admin'))
        self.client.force_login(staff)
        self.assertRedirects(self.client.get(self.list_url), reverse('dashboard'), fetch_redirect_response=False)
        self.client.force_login(self.admin)
        response = self.client.get(self.list_url)
        self.assertContains(response, 'New banner')
        self.assertContains(response, 'href="%s"' % self.list_url)

    def test_add_banner_goes_live_in_the_app_at_the_end_and_is_audited(self):
        self.assertRedirects(self.add(title='First'), self.list_url)
        self.add(title='Second', cta_text='Shop now', cta_url='https://skillsikka.com/sale')
        first, second = Advertisement.objects.order_by('pk')
        self.assertEqual((first.display_order, second.display_order), (1, 2))
        self.assertEqual((second.created_by, second.cta_url, second.is_active), (self.admin, 'https://skillsikka.com/sale', True))
        self.assertTrue(second.banner_image.name.startswith('advertisements/'))
        self.assertEqual(self.app_banner_ids(), [first.pk, second.pk])
        self.assertTrue(AuditLog.objects.filter(action='create', target_type='advertisement', target_id=second.pk).exists())

    def test_bad_input_is_explained_and_nothing_is_saved(self):
        not_an_image = SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')
        cases = [
            ('banner_image', {'banner_image': ''}),
            ('banner_image', {'banner_image': not_an_image}),
            ('banner_image', {'banner_image': SimpleUploadedFile('x.gif', b'GIF89a', content_type='image/gif')}),
            ('cta_url', {'cta_url': 'ftp://example.com/x'}),
            ('ends_at', {'starts_at': '2030-01-10T10:00', 'ends_at': '2030-01-09T10:00'}),
            ('title', {'title': ''}),
        ]
        for field, overrides in cases:
            with self.subTest(field=field, overrides=list(overrides)):
                response = self.add(expect_created=False, **overrides)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors.get(field), response.context['form'].errors)

    def test_dates_are_nepal_time_and_status_follows_them(self):
        self.add(title='Scheduled', starts_at='2030-01-10T10:00')
        banner = Advertisement.objects.get()
        self.assertEqual(banner.starts_at, datetime(2030, 1, 10, 4, 15, tzinfo=dt_timezone.utc))
        self.assertEqual(self.app_banner_ids(), [])
        self.add(title='Expired', starts_at='2020-01-01T10:00', ends_at='2020-01-02T10:00')
        self.add(title='Off', is_active='')
        self.add(title='Live')
        page = self.client.get(self.list_url)
        statuses = {b.title: b.status for b in page.context['banners']}
        self.assertEqual(statuses, {'Scheduled': 'scheduled', 'Expired': 'expired', 'Off': 'off', 'Live': 'live'})
        self.assertEqual(page.context['live_count'], 1)
        for label in ('Scheduled', 'Expired', 'Off', 'Live'):
            self.assertContains(page, f'>{label}</span>')

    def test_edit_keeps_or_replaces_the_image(self):
        self.add()
        banner = Advertisement.objects.get()
        url = reverse('edit_banner', args=[banner.pk])
        old_name = banner.banner_image.name
        self.assertContains(self.client.get(url), 'Leave empty to keep the current image')
        data = {'title': 'Renamed', 'description': '', 'cta_text': '', 'cta_url': '', 'starts_at': '', 'ends_at': '', 'is_active': 'on'}
        self.assertRedirects(self.client.post(url, data), self.list_url)
        banner.refresh_from_db()
        self.assertEqual((banner.title, banner.banner_image.name), ('Renamed', old_name))
        storage = banner.banner_image.storage
        self.client.post(url, {**data, 'banner_image': png('new.png')})
        banner.refresh_from_db()
        self.assertNotEqual(banner.banner_image.name, old_name)
        self.assertFalse(storage.exists(old_name))
        self.assertTrue(storage.exists(banner.banner_image.name))
        self.assertTrue(AuditLog.objects.filter(action='update', target_id=banner.pk).exists())

    def test_turn_off_and_on(self):
        self.add()
        banner = Advertisement.objects.get()
        self.assertRedirects(self.act(banner, 'toggle'), self.list_url)
        banner.refresh_from_db()
        self.assertFalse(banner.is_active)
        self.assertEqual(self.app_banner_ids(), [])
        self.act(banner, 'toggle')
        banner.refresh_from_db()
        self.assertTrue(banner.is_active)
        self.assertEqual(self.app_banner_ids(), [banner.pk])
        self.assertEqual(AuditLog.objects.filter(target_id=banner.pk, action__in=['activate', 'deactivate']).count(), 2)

    def test_move_up_and_down_even_with_old_tied_orders(self):
        for title in ('A', 'B', 'C'):
            self.add(title=title)
        Advertisement.objects.update(display_order=0)  # rows from before this page all share 0
        a, b, c = Advertisement.objects.order_by('pk')
        self.act(c, 'up')
        self.assertEqual(self.app_banner_ids(), [a.pk, c.pk, b.pk])
        self.act(a, 'down')
        self.assertEqual(self.app_banner_ids(), [c.pk, a.pk, b.pk])
        self.act(c, 'up')      # already first: nothing changes
        self.act(b, 'down')    # already last: nothing changes
        self.assertEqual(self.app_banner_ids(), [c.pk, a.pk, b.pk])

    def test_archive_and_restore(self):
        for title in ('A', 'B'):
            self.add(title=title)
        a, b = Advertisement.objects.order_by('pk')
        self.act(a, 'archive')
        a.refresh_from_db()
        self.assertIsNotNone(a.archived_at)
        self.assertFalse(a.is_active)
        self.assertEqual(self.app_banner_ids(), [b.pk])
        page = self.client.get(self.list_url)
        self.assertEqual([x.pk for x in page.context['archived']], [a.pk])
        self.assertRedirects(self.client.get(reverse('edit_banner', args=[a.pk])), self.list_url, fetch_redirect_response=False)
        self.act(a, 'toggle')
        a.refresh_from_db()
        self.assertFalse(a.is_active)  # archived banners cannot be switched on
        self.act(a, 'restore')
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertIsNone(a.archived_at)
        self.assertFalse(a.is_active)  # comes back off, at the end
        self.assertGreater(a.display_order, b.display_order)
        self.act(a, 'toggle')
        self.assertEqual(self.app_banner_ids(), [b.pk, a.pk])

    def test_unknown_action_and_get_are_refused(self):
        self.add()
        banner = Advertisement.objects.get()
        self.act(banner, 'explode')
        self.assertEqual(self.client.get(reverse('banner_action', args=[banner.pk])).status_code, 405)
        self.assertEqual(self.act(Advertisement(pk=999999), 'toggle').status_code, 404)


class HomeFeedBannerLimitTests(TestCase):
    def test_home_shows_up_to_five_banners(self):
        student = User.objects.create_user(email='home-banners@example.com', name='Student', role=Role.objects.get(name='student'))
        StudentProfile.objects.create(user=student)
        for i in range(6):
            Advertisement.objects.create(title=f'Ad {i}', banner_image=f'advertisements/{i}.png', is_active=True, display_order=i)
        api = APIClient()
        api.force_authenticate(student)
        self.assertEqual(len(api.get('/api/v1/home/').data['advertisements']), 5)
