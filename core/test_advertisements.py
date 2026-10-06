import io
import json
import shutil
import tempfile
import uuid
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, LiveServerTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Advertisement, AuditLog, Role, User


def image_upload(name='banner.png', format='PNG', content_type='image/png', size=(8, 8)):
    buffer = io.BytesIO()
    Image.new('RGB', size, 'blue').save(buffer, format=format)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


class AdvertisementTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp(prefix='skillsikka-ad-tests-')
        self.settings_override = override_settings(MEDIA_ROOT=self.media, STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        })
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        cache.clear()
        self.admin = User.objects.create_user(email='ad-admin@example.com', name='Admin',
            role=Role.objects.get_or_create(name='super_admin')[0])
        self.student = User.objects.create_user(email='ad-student@example.com', name='Student',
            role=Role.objects.get_or_create(name='student')[0])
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = '/api/v1/admin/advertisements/'
        self.display = '/api/v1/advertisements/'

    def create(self, **fields):
        fields.setdefault('title', 'Dynamic advertisement')
        fields.setdefault('banner_image', image_upload())
        return self.client.post(self.url, fields, format='multipart')

    def detail(self, pk):
        return self.url + str(pk) + '/'

    def ad(self, **fields):
        fields.setdefault('title', 'Managed content')
        fields.setdefault('banner_image', image_upload())
        fields.setdefault('created_by', self.admin)
        return Advertisement.objects.create(**fields)

    def test_empty_catalogue_and_authenticated_read_only(self):
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get(self.display).data, [])
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(self.client, method)(self.display).status_code, 405)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.display).status_code, 401)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_visibility_schedules_boundaries_multiple_and_safe_fields(self):
        now = timezone.now()
        visible = [self.ad(is_active=True), self.ad(is_active=True, starts_at=now),
                   self.ad(is_active=True, ends_at=now), self.ad(is_active=True, starts_at=now, ends_at=now)]
        self.ad(is_active=False)
        self.ad(is_active=True, starts_at=now + timedelta(seconds=1))
        self.ad(is_active=True, ends_at=now - timedelta(seconds=1))
        self.ad(is_active=True, archived_at=now)
        self.client.force_authenticate(self.student)
        with patch('core.advertisement_views.timezone.now', return_value=now) as clock:
            response = self.client.get(self.display)
        clock.assert_called_once_with()
        self.assertEqual([r['id'] for r in response.data], [a.pk for a in visible])
        self.assertEqual(set(response.data[0]), {'id', 'title', 'description', 'banner_image', 'cta_text',
            'cta_url', 'starts_at', 'ends_at', 'display_order'})
        self.assertTrue(response.data[0]['banner_image'].startswith('http://testserver/'))

    def test_display_order_then_id(self):
        a = self.ad(is_active=True, display_order=2)
        b = self.ad(is_active=True, display_order=0)
        c = self.ad(is_active=True, display_order=0)
        self.client.force_authenticate(self.student)
        self.assertEqual([r['id'] for r in self.client.get(self.display).data], [b.pk, c.pk, a.pk])

    def test_admin_create_list_detail_and_server_controlled_fields(self):
        response = self.create(created_by=self.student.pk, archived_at=timezone.now().isoformat(),
                               created_at='2000-01-01T00:00:00Z', description='Custom content')
        self.assertEqual(response.status_code, 201, response.data)
        ad = Advertisement.objects.get(pk=response.data['id'])
        self.assertEqual(ad.created_by, self.admin)
        self.assertIsNone(ad.archived_at)
        self.assertFalse(ad.is_active)
        self.assertGreater(ad.created_at.year, 2000)
        self.assertEqual(self.client.get(self.url).data['count'], 1)
        self.assertEqual(self.client.get(self.detail(ad.pk)).data['description'], 'Custom content')
        log = AuditLog.objects.get(target_type='advertisement', target_id=ad.pk)
        self.assertEqual(log.action, 'create')
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.metadata['after']['title'], ad.title)
        self.assertIsNone(log.metadata['before'])

    def test_patch_update_activation_deactivation_and_creator_unchanged(self):
        ad = self.ad()
        response = self.client.patch(self.detail(ad.pk), {'title': 'Changed', 'display_order': 3,
            'created_by': self.student.pk, 'is_active': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        ad.refresh_from_db()
        self.assertEqual(ad.title, 'Changed')
        self.assertEqual(ad.display_order, 3)
        self.assertEqual(ad.created_by, self.admin)
        logs = AuditLog.objects.filter(target_id=ad.pk).order_by('pk')
        self.assertEqual(list(logs.values_list('action', flat=True)), ['update', 'activate'])
        self.assertFalse(logs.last().metadata['before']['is_active'])
        self.assertTrue(logs.last().metadata['after']['is_active'])
        self.assertEqual(self.client.patch(self.detail(ad.pk), {'is_active': False}, format='json').status_code, 200)
        self.assertEqual(list(AuditLog.objects.filter(target_id=ad.pk).order_by('pk').values_list('action', flat=True)),
                         ['update', 'activate', 'update', 'deactivate'])

    def test_delete_archives_preserves_image_and_admin_history(self):
        ad = self.ad(is_active=True)
        original = ad.banner_image.name
        self.assertEqual(self.client.delete(self.detail(ad.pk)).status_code, 204)
        ad.refresh_from_db()
        self.assertFalse(ad.is_active)
        self.assertIsNotNone(ad.archived_at)
        self.assertTrue(ad.banner_image.storage.exists(original))
        self.assertEqual(self.client.get(self.detail(ad.pk)).status_code, 200)
        self.assertEqual(self.client.get(self.url).data['count'], 1)
        log = AuditLog.objects.get(target_type='advertisement', target_id=ad.pk)
        self.assertEqual(log.action, 'delete')
        self.assertTrue(log.metadata['archived'])
        self.assertEqual(self.client.patch(self.detail(ad.pk), {'is_active': True}, format='json').status_code, 400)
        self.assertEqual(self.client.delete(self.detail(ad.pk)).status_code, 204)
        self.assertEqual(AuditLog.objects.filter(target_id=ad.pk).count(), 1)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get(self.display).data, [])

    def test_schedule_invalid_create_and_all_partial_updates(self):
        now = timezone.now()
        response = self.create(starts_at=now.isoformat(), ends_at=(now-timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Advertisement.objects.exists())
        ad = self.ad(starts_at=now, ends_at=now+timedelta(days=2))
        for payload in ({'starts_at': (now+timedelta(days=3)).isoformat()},
                        {'ends_at': (now-timedelta(days=1)).isoformat()},
                        {'starts_at': (now+timedelta(days=4)).isoformat(), 'ends_at': now.isoformat()}):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.patch(self.detail(ad.pk), payload, format='json').status_code, 400)
                ad.refresh_from_db()
                self.assertEqual(ad.starts_at, now)
                self.assertEqual(ad.ends_at, now+timedelta(days=2))
        self.assertEqual(self.client.patch(self.detail(ad.pk), {'starts_at': None, 'ends_at': None}, format='json').status_code, 200)

    def test_valid_images_jpeg_and_png_unique_storage_names(self):
        for filename, fmt, mime in [('client.jpg', 'JPEG', 'image/jpeg'), ('client.jpeg', 'JPEG', 'image/jpeg'), ('client.png', 'PNG', 'image/png')]:
            with self.subTest(fmt=fmt, filename=filename):
                response = self.create(banner_image=image_upload(filename, fmt, mime))
                self.assertEqual(response.status_code, 201, response.data)
                name = Advertisement.objects.get(pk=response.data['id']).banner_image.name
                self.assertTrue(name.startswith('advertisements/'))
                self.assertNotIn('client', name)
                self.assertEqual(len(Path(name).stem), 32)
                uuid.UUID(Path(name).stem)

    def test_unsafe_filename_not_used(self):
        response = self.create(banner_image=image_upload('../../unsafe client.png'))
        self.assertEqual(response.status_code, 201, response.data)
        name = Advertisement.objects.get(pk=response.data['id']).banner_image.name
        self.assertNotIn('unsafe', name)
        self.assertNotIn('..', name)

    def test_invalid_images_rejected_without_files_or_rows(self):
        png = image_upload().read()
        jpeg = image_upload('cut.jpg', 'JPEG', 'image/jpeg').read()
        uploads = [
            SimpleUploadedFile('big.png', b'0'*(5*1024*1024+1), content_type='image/png'),
            SimpleUploadedFile('bad.png', b'not-an-image', content_type='image/png'),
            SimpleUploadedFile('cut.png', png[:len(png)//2], content_type='image/png'),
            SimpleUploadedFile('cut.jpg', jpeg[:-2], content_type='image/jpeg'),
            image_upload('wrong.jpg', 'PNG', 'image/jpeg'),
            image_upload('wrong.png', 'PNG', 'image/jpeg'),
            image_upload('bad.gif', 'PNG', 'image/png'),
            image_upload('bad.png', 'PNG', 'application/octet-stream'),
            image_upload(size=(8193, 1)),
            image_upload(size=(5000, 4100)),
        ]
        for upload in uploads:
            with self.subTest(name=upload.name):
                response = self.create(banner_image=upload)
                self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(Advertisement.objects.count(), 0)
        self.assertEqual(list(Path(self.media).rglob('*')), [])

    def test_required_image_title_limits_and_nonnegative_order(self):
        for payload in ({'title': 'No image'}, {'title': '', 'banner_image': image_upload()},
                        {'title': 'x'*201, 'banner_image': image_upload()},
                        {'title': 'Invalid order', 'banner_image': image_upload(), 'display_order': -1}):
            self.assertEqual(self.client.post(self.url, payload, format='multipart').status_code, 400)

    def test_cta_optional_valid_urls_and_invalid_schemes(self):
        ad = self.ad()
        for url in ('javascript:alert(1)', 'file:///etc/passwd', 'ftp://example.com/file', 'not a URL'):
            with self.subTest(url=url):
                self.assertEqual(self.client.patch(self.detail(ad.pk), {'cta_url': url}, format='json').status_code, 400)
        for url in ('https://example.com/course', 'http://example.com/', ''):
            self.assertEqual(self.client.patch(self.detail(ad.pk), {'cta_url': url}, format='json').status_code, 200)
        self.assertEqual(self.client.patch(self.detail(ad.pk), {'cta_text': 'x'*101}, format='json').status_code, 400)

    def test_other_roles_and_staff_cannot_manage_any_method(self):
        ad = self.ad()
        for role_name in ('student', 'instructor', 'local_authority', 'ministry', 'school_admin'):
            user = User.objects.create_user(email=role_name+'-denied@example.com', name='Denied',
                role=Role.objects.get_or_create(name=role_name)[0], is_staff=True)
            self.client.force_authenticate(user)
            for method, path in [('get',self.url),('post',self.url),('get',self.detail(ad.pk)),
                                 ('patch',self.detail(ad.pk)),('delete',self.detail(ad.pk))]:
                with self.subTest(role=role_name, method=method):
                    self.assertEqual(getattr(self.client,method)(path).status_code,403)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_superuser_without_super_admin_role_is_allowed(self):
        self.student.is_superuser = True
        self.student.save()
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_existing_super_admin_audit_api_lists_advertisement_records(self):
        response = self.create()
        self.assertEqual(response.status_code, 201)
        response = self.client.get('/api/v1/admin/audit-logs/?target_type=advertisement')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.client.force_authenticate(self.student)
        self.assertEqual(self.client.get('/api/v1/admin/audit-logs/').status_code, 403)

    def test_failed_create_rolls_back_row_audit_and_new_file(self):
        with patch('core.advertisement_views._create_audit_log', side_effect=RuntimeError('Audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.create()
        self.assertEqual(Advertisement.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)
        self.assertEqual([p for p in Path(self.media).rglob('*') if p.is_file()], [])

    def test_failed_image_update_preserves_old_image_and_removes_new(self):
        ad = self.ad()
        old = ad.banner_image.name
        with patch('core.advertisement_views._create_audit_log', side_effect=RuntimeError('Audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.patch(self.detail(ad.pk), {'banner_image': image_upload(), 'title': 'Failed'}, format='multipart')
        ad.refresh_from_db()
        self.assertEqual(ad.banner_image.name, old)
        self.assertEqual(ad.title, 'Managed content')
        self.assertEqual(len([p for p in Path(self.media).rglob('*') if p.is_file()]), 1)

    def test_failed_cleanup_logs_error_without_masking_original_failure(self):
        storage = Advertisement._meta.get_field('banner_image').storage
        with patch('core.advertisement_views._create_audit_log', side_effect=RuntimeError('Audit unavailable')):
            with patch.object(storage, 'delete', side_effect=OSError('Storage unavailable')):
                with self.assertLogs('core.advertisement_views', level='ERROR'):
                    with self.assertRaisesRegex(RuntimeError, 'Audit unavailable'):
                        self.create()
        self.assertFalse(Advertisement.objects.exists())

    def test_replaced_image_removed_only_after_commit(self):
        ad = self.ad()
        old = ad.banner_image.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(self.detail(ad.pk), {'banner_image': image_upload()}, format='multipart')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(ad.banner_image.storage.exists(old))
        ad.refresh_from_db()
        self.assertNotEqual(ad.banner_image.name, old)
        self.assertFalse(ad.banner_image.storage.exists(old))
        self.assertTrue(ad.banner_image.storage.exists(ad.banner_image.name))

    def test_archive_audit_failure_rolls_back_archive(self):
        ad = self.ad(is_active=True)
        with patch('core.advertisement_views._create_audit_log', side_effect=RuntimeError('Audit unavailable')):
            with self.assertRaises(RuntimeError):
                self.client.delete(self.detail(ad.pk))
        ad.refresh_from_db()
        self.assertIsNone(ad.archived_at)
        self.assertTrue(ad.is_active)


class AdvertisementLiveTests(LiveServerTestCase):
    def setUp(self):
        cache.clear()
        self.media = tempfile.mkdtemp(prefix='skillsikka-ad-live-')
        self.override = override_settings(MEDIA_ROOT=self.media, STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        })
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        self.password = 'Live-advertisement-Strong-123!'
        self.admin = User.objects.create_user(email='live-ad-admin@example.com', name='Admin', password=self.password,
            role=Role.objects.get_or_create(name='super_admin')[0])
        self.student = User.objects.create_user(email='live-ad-student@example.com', name='Student', password=self.password,
            role=Role.objects.get_or_create(name='student')[0])

    def request(self, path, payload=None, token=None, method=None, multipart=False):
        headers = {}
        data = None
        if token:
            headers['Authorization'] = 'Bearer '+token
        if multipart:
            boundary = 'SkillSikka'+uuid.uuid4().hex
            image = image_upload().read()
            data = (f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nDynamic live content\r\n'
                    f'--{boundary}\r\nContent-Disposition: form-data; name="banner_image"; filename="client.png"\r\n'
                    f'Content-Type: image/png\r\n\r\n').encode()+image+f'\r\n--{boundary}--\r\n'.encode()
            headers['Content-Type'] = 'multipart/form-data; boundary='+boundary
        elif payload is not None:
            data = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.live_server_url+'/api/v1/'+path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_real_http_login_create_activate_update_archive_and_audit(self):
        status, body = self.request('login/', {'email': self.admin.email, 'password': self.password})
        self.assertEqual(status, 200, body)
        admin_token = body['tokens']['access']
        status, body = self.request('login/', {'email': self.student.email, 'password': self.password})
        self.assertEqual(status, 200, body)
        student_token = body['tokens']['access']
        status, body = self.request('admin/advertisements/', token=admin_token, method='POST', multipart=True)
        self.assertEqual(status, 201, body)
        pk = body['id']
        self.assertFalse(body['is_active'])
        self.assertEqual(self.request('advertisements/', token=student_token), (200, []))
        path = f'admin/advertisements/{pk}/'
        self.assertEqual(self.request(path, {'is_active': True}, admin_token, method='PATCH')[0], 200)
        self.assertEqual(self.request('advertisements/', token=student_token)[1][0]['id'], pk)
        self.assertEqual(self.request(path, {'title': 'Edited live content', 'display_order': 5}, admin_token, method='PATCH')[0], 200)
        visible = self.request('advertisements/', token=student_token)[1][0]
        self.assertEqual((visible['title'], visible['display_order']), ('Edited live content', 5))
        self.assertEqual(self.request(path, token=admin_token, method='DELETE')[0], 204)
        ad = Advertisement.objects.get(pk=pk)
        self.assertIsNotNone(ad.archived_at)
        self.assertTrue(ad.banner_image.storage.exists(ad.banner_image.name))
        self.assertEqual(self.request('advertisements/', token=student_token), (200, []))
        self.assertEqual(list(AuditLog.objects.filter(target_type='advertisement', target_id=pk).order_by('pk').values_list('action', flat=True)),
                         ['create', 'update', 'activate', 'update', 'delete'])
