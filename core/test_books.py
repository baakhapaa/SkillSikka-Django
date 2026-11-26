"""Phase 1 books: compatibility, private uploads, dashboard and real migration."""
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from fnmatch import fnmatchcase
import stat
from tempfile import TemporaryDirectory
import zipfile

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .book_files import PrivateBookStorage, check_book_storage, validate_book_source
from .models import EBook, Grade, Role, Subject, User


PDF = b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n'
TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def pdf(name='book.pdf', body=PDF):
    return SimpleUploadedFile(name, body, content_type='application/octet-stream')


def epub(extra=None):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('mimetype', b'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        archive.writestr('META-INF/container.xml', b'<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/package.opf"/></rootfiles></container>')
        archive.writestr('OEBPS/package.opf', b'<package/>')
        for name, body in (extra or {}).items():
            archive.writestr(name, body)
    return SimpleUploadedFile('book.epub', stream.getvalue(), content_type='text/plain')


def cover(name='cover.png'):
    stream = BytesIO()
    Image.new('RGB', (8, 8), 'blue').save(stream, format='PNG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type='text/plain')


@override_settings(STORAGES=TEST_STORAGES)
class BookSectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = cls.user('admin', 'super_admin')
        cls.owner = cls.user('owner', 'instructor', verification_status='verified')
        cls.other = cls.user('other', 'instructor', verification_status='verified')
        cls.unverified = cls.user('unverified', 'instructor', verification_status='pending')
        cls.student = cls.user('student', 'student')
        cls.subject = Subject.objects.create(name='Book mathematics')
        cls.grade = Grade.objects.first()

    @classmethod
    def user(cls, name, role, **kwargs):
        return User.objects.create_user(email=f'books-{name}@example.com', name=name,
            role=Role.objects.get(name=role), **kwargs)

    def setUp(self):
        # API matrices must not inherit another test's throttle history. Use an
        # isolated local cache rather than weakening production throttle rates.
        self.cache_override = override_settings(CACHES={'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': f'book-test-{id(self)}',
        }})
        self.cache_override.enable()
        self.addCleanup(self.cache_override.disable)
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.settings_override = override_settings(MEDIA_ROOT=root / 'public', BOOK_PRIVATE_ROOT=root / 'private')
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.list_url = reverse('api-ebook-list-create')

    def book(self, **kwargs):
        values = dict(title='Legacy book', author='Author', file_url='https://legacy.example.com/paid.pdf', uploaded_by=self.owner)
        values.update(kwargs)
        return EBook.objects.create(**values)

    def detail(self, book):
        return reverse('api-ebook-detail', args=[book.pk])

    def content(self, book):
        return reverse('api-ebook-content', args=[book.pk])

    def upload(self, **kwargs):
        values = {'title': 'Uploaded book', 'source_file': pdf()}
        values.update(kwargs)
        return self.api.post(self.list_url, values, format='multipart')

    def admin_payload(self, **kwargs):
        values = {'title': 'Dashboard book', 'author': 'Writer', 'highlights': '["Clear examples"]',
                  'currency': 'NPR', 'price': '', 'source_file': pdf()}
        values.update(kwargs)
        return values

    def test_legacy_create_and_update_contract(self):
        response = self.api.post(self.list_url, {'title': 'Old client', 'file_url': 'https://legacy.example.com/book.pdf',
            'subject': self.subject.pk, 'grade': self.grade.pk}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        book = EBook.objects.get(pk=response.data['id'])
        self.assertEqual(book.uploaded_by, self.owner)
        self.assertIsNone(book.price)
        self.assertEqual(book.file_url, 'https://legacy.example.com/book.pdf')
        self.assertEqual(response.data['file_url'], '')
        self.assertEqual(self.api.patch(self.detail(book), {'title': 'Updated'}, format='json').status_code, 200)

    def test_catalog_filters_and_original_metadata(self):
        book = self.book(is_published=True, subject=self.subject, grade=self.grade)
        self.book(title='Other', is_published=True)
        self.api.force_authenticate(self.student)
        response = self.api.get(self.list_url, {'subject': self.subject.pk, 'grade': self.grade.pk})
        self.assertEqual([row['id'] for row in response.data], [book.pk])
        self.assertEqual(response.data[0]['subject_name'], self.subject.name)
        self.assertEqual(response.data[0]['uploaded_by_name'], self.owner.name)

    def test_legacy_get_put_preserves_draft_and_published_source(self):
        for published in (False, True):
            with self.subTest(published=published):
                book = self.book(is_published=published)
                original = book.file_url
                payload = dict(self.api.get(self.detail(book)).data)
                self.assertEqual(payload['file_url'], '')
                self.assertNotIn(original, str(payload))
                payload['title'] = 'Metadata edit'
                response = self.api.put(self.detail(book), payload, format='json')
                self.assertEqual(response.status_code, 200, response.data)
                book.refresh_from_db()
                self.assertEqual(book.file_url, original)
                self.assertEqual(book.is_published, published)
                self.assertEqual(book.title, 'Metadata edit')
                self.assertEqual(response.data['file_url'], '')

    def test_masked_patch_placeholder_also_preserves_source(self):
        book = self.book()
        original = book.file_url
        response = self.api.patch(self.detail(book), {'file_url': '', 'clear_file_url': False}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        book.refresh_from_db()
        self.assertEqual(book.file_url, original)

    def test_explicit_clear_allows_current_owner_and_admin(self):
        for user in (self.owner, self.admin):
            with self.subTest(user=user.pk):
                book = self.book()
                self.api.force_authenticate(user)
                response = self.api.patch(self.detail(book), {'clear_file_url': True}, format='json')
                self.assertEqual(response.status_code, 200, response.data)
                book.refresh_from_db()
                self.assertEqual(book.file_url, '')
                self.assertFalse(book.is_published)
                self.assertNotIn('clear_file_url', response.data)

    def test_clear_cannot_remove_last_source_from_published_book(self):
        book = self.book(is_published=True)
        original = book.file_url
        response = self.api.patch(self.detail(book), {'clear_file_url': True}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        book.refresh_from_db()
        self.assertEqual(book.file_url, original)
        self.assertTrue(book.is_published)
        # Explicitly unpublishing in the same authorized operation is safe.
        response = self.api.patch(self.detail(book), {'clear_file_url': True, 'is_published': False}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        book.refresh_from_db()
        self.assertEqual(book.file_url, '')
        self.assertFalse(book.is_published)

    def test_clear_published_legacy_url_with_private_replacement(self):
        created = self.upload(is_published='true', file_url='https://example.com/old.pdf')
        book = EBook.objects.get(pk=created.data['id'])
        source_name = book.source_file.name
        response = self.api.patch(self.detail(book), {'clear_file_url': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        book.refresh_from_db()
        self.assertEqual(book.file_url, '')
        self.assertEqual(book.source_file.name, source_name)
        self.assertTrue(book.is_published)

    def test_unauthorized_clear_does_not_modify_reference(self):
        created = self.upload(is_published='true', file_url='https://example.com/old.pdf')
        book = EBook.objects.get(pk=created.data['id'])
        original = book.file_url
        for user in (self.other, self.student):
            self.api.force_authenticate(user)
            response = self.api.patch(self.detail(book), {'clear_file_url': True}, format='json')
            self.assertEqual(response.status_code, 403)
            book.refresh_from_db()
            self.assertEqual(book.file_url, original)
            self.assertNotIn(original, str(response.data))
        self.owner.role = self.student.role
        self.owner.save(update_fields=['role'])
        self.api.force_authenticate(self.owner)
        self.assertEqual(self.api.patch(self.detail(book), {'clear_file_url': True}, format='json').status_code, 403)
        book.refresh_from_db()
        self.assertEqual(book.file_url, original)

    def test_clear_rejects_creation_and_conflicting_replacement(self):
        response = self.api.post(self.list_url, {'title': 'No reference yet', 'clear_file_url': True}, format='json')
        self.assertEqual(response.status_code, 400)
        book = self.book()
        original = book.file_url
        response = self.api.patch(self.detail(book), {'clear_file_url': True, 'file_url': 'https://example.com/new.pdf'}, format='json')
        self.assertEqual(response.status_code, 400)
        book.refresh_from_db()
        self.assertEqual(book.file_url, original)

    def test_complete_metadata(self):
        response = self.api.post(self.list_url, {'title': 'Metadata', 'file_url': 'https://example.com/book.epub',
            'category': 'Technology', 'difficulty': 'advanced', 'highlights': ['One', 'Two'],
            'price': '125.50', 'currency': 'NPR'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['price'], '125.50')
        self.assertEqual(response.data['highlights'], ['One', 'Two'])

    def test_invalid_metadata(self):
        for field, value in [('difficulty', 'expert'), ('currency', 'USD'), ('highlights', {'x': 1}),
                             ('highlights', ['']), ('highlights', ['x'] * 31), ('highlights', ['x' * 501])]:
            with self.subTest(field=field, value=value):
                response = self.api.post(self.list_url, {'title': 'Invalid', 'file_url': 'https://example.com/book.pdf', field: value}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn(field, response.data)

    def test_negative_and_excess_precision_price_rejected(self):
        for price in ['-0.01', '1.001', 'NaN', 'Infinity']:
            response = self.api.post(self.list_url, {'title': 'Bad price', 'file_url': 'https://example.com/book.pdf', 'price': price}, format='json')
            self.assertEqual(response.status_code, 400, response.data)

    def test_zero_price_is_explicit_and_does_not_grant_content(self):
        response = self.upload(price='0', is_published='true')
        self.assertEqual(response.status_code, 201, response.data)
        book = EBook.objects.get(pk=response.data['id'])
        self.assertEqual(book.price, Decimal('0'))
        self.api.force_authenticate(self.student)
        self.assertEqual(self.api.get(self.content(book)).status_code, 403)

    def test_database_rejects_negative_price_and_wrong_currency(self):
        for values in [{'price': -1}, {'currency': 'USD'}]:
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                self.book(**values)

    def test_content_reference_required(self):
        response = self.api.post(self.list_url, {'title': 'No source', 'is_published': True}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_metadata_only_draft_can_be_saved_but_not_published(self):
        response = self.api.post(self.list_url, {'title': 'Future upload'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        book = EBook.objects.get(pk=response.data['id'])
        self.assertFalse(book.is_published)
        response = self.api.patch(self.detail(book), {'is_published': True}, format='json')
        self.assertEqual(response.status_code, 400)
        self.client.force_login(self.admin)
        response = self.client.post(reverse('add_book'), {'title': 'Dashboard draft', 'currency': 'NPR', 'highlights': '[]'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EBook.objects.filter(title='Dashboard draft', is_published=False).exists())

    def test_pdf_upload_is_private_and_randomized(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        book = EBook.objects.get(pk=response.data['id'])
        self.assertEqual(book.file_format, 'pdf')
        self.assertRegex(book.source_file.name, r'^content/[0-9a-f]{32}\.pdf$')
        self.assertTrue(Path(book.source_file.path).is_relative_to(Path(self.tmp.name) / 'private'))
        self.assertFalse((Path(self.tmp.name) / 'public' / book.source_file.name).exists())
        with self.assertRaises(ValueError):
            _ = book.source_file.url

    def test_epub_upload_checks_content_not_client_mime(self):
        response = self.upload(source_file=epub())
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['file_format'], 'epub')

    def test_cover_upload_and_public_cover_contract(self):
        response = self.upload(cover_image=cover())
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('/media/book-covers/', response.data['cover_url'])
        self.assertNotIn('cover_image', response.data)

    def test_author_photo_upload_and_url(self):
        response = self.upload(author_photo=cover('author.png'))
        self.assertEqual(response.status_code, 201, response.data)
        url = response.data['author_photo_url']
        self.assertTrue(url.startswith('http://testserver/media/book-authors/'), url)
        self.assertNotIn('author_photo', response.data)
        book = EBook.objects.get(pk=response.data['id'])
        self.assertEqual(self.api.get(self.detail(book)).data['author_photo_url'], url)
        row = next(row for row in self.api.get(self.list_url).data if row['id'] == book.pk)
        self.assertEqual(row['author_photo_url'], url)
        # No photo is an empty string, never a missing key or null.
        self.assertEqual(self.api.get(self.detail(self.book())).data['author_photo_url'], '')
        fake = SimpleUploadedFile('fake.png', b'<script>bad</script>', content_type='image/png')
        self.assertEqual(self.upload(author_photo=fake).status_code, 400)

    def test_admin_uploads_author_photo(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('add_book'), self.admin_payload(author_photo=cover('author.png')))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(EBook.objects.get(title='Dashboard book').author_photo.name.startswith('book-authors/'))

    def test_invalid_signatures_and_extensions(self):
        for upload in [pdf(body=b'<html>fake</html>'), pdf(name='fake.epub'), pdf(name='fake.exe'),
                       pdf(body=b'%PDF-1.7\nno end marker'), cover(name='fake.jpg')]:
            with self.subTest(name=upload.name):
                response = self.upload(source_file=upload)
                self.assertEqual(response.status_code, 400, response.data)

    def test_fake_cover_is_rejected(self):
        response = self.upload(cover_image=SimpleUploadedFile('fake.png', b'<script>bad</script>', content_type='image/png'))
        self.assertEqual(response.status_code, 400)

    @override_settings(BOOK_MAX_UPLOAD_BYTES=10)
    def test_oversized_source_rejected_before_storage(self):
        self.assertEqual(self.upload().status_code, 400)
        self.assertFalse((Path(self.tmp.name) / 'private').exists())

    @override_settings(BOOK_MAX_COVER_BYTES=10)
    def test_oversized_cover_rejected(self):
        self.assertEqual(self.upload(cover_image=cover()).status_code, 400)

    def test_unsafe_client_filename_cannot_control_storage_path(self):
        response = self.upload(source_file=pdf('../../escape.pdf'))
        self.assertEqual(response.status_code, 201, response.data)
        book = EBook.objects.get(pk=response.data['id'])
        self.assertRegex(book.source_file.name, r'^content/[0-9a-f]{32}\.pdf$')
        self.assertNotIn('escape', book.source_file.name)

    def test_unsafe_epub_paths_rejected(self):
        for name in ['../escape', '/absolute', 'C:/file', 'dir\\file', 'a/../file', 'a//file']:
            with self.subTest(name=name):
                upload = epub({name: b'x'})
                if '\\' in name:
                    # Windows zipfile normalizes names when writing. Preserve the
                    # hostile original bytes in both local and central headers.
                    body = upload.read().replace(name.replace('\\', '/').encode(), name.encode())
                    upload = SimpleUploadedFile('unsafe.epub', body)
                self.assertEqual(self.upload(source_file=upload).status_code, 400)

    def test_epub_symlink_rejected(self):
        upload = epub()
        stream = BytesIO(upload.read())
        with zipfile.ZipFile(stream, 'a') as archive:
            entry = zipfile.ZipInfo('link')
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, '../secret')
        response = self.upload(source_file=SimpleUploadedFile('link.epub', stream.getvalue()))
        self.assertEqual(response.status_code, 400)

    def test_epub_bomb_and_duplicates_rejected(self):
        stream = BytesIO(epub().read())
        with zipfile.ZipFile(stream, 'a') as archive:
            archive.writestr('bomb', b'x' * 100_000, compress_type=zipfile.ZIP_DEFLATED)
        self.assertEqual(self.upload(source_file=SimpleUploadedFile('bomb.epub', stream.getvalue())).status_code, 400)
        self.assertEqual(self.upload(source_file=epub({'MIMETYPE': b'collision'})).status_code, 400)

    def test_epub_container_and_mimetype_required(self):
        stream = BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('unrelated.txt', 'not a book')
        self.assertEqual(self.upload(source_file=SimpleUploadedFile('fake.epub', stream.getvalue())).status_code, 400)

    def test_epub_dtd_rejected(self):
        stream = BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('mimetype', b'application/epub+zip')
            archive.writestr('META-INF/container.xml', b'<!DOCTYPE x [<!ENTITY x "unsafe">]><container/>')
        with self.assertRaises(ValidationError):
            validate_book_source(SimpleUploadedFile('dtd.epub', stream.getvalue()))

    def test_private_root_cannot_overlap_public_media(self):
        with override_settings(BOOK_PRIVATE_ROOT=Path(self.tmp.name) / 'public' / 'books'):
            self.assertTrue(check_book_storage(None))
            from django.core.exceptions import ImproperlyConfigured
            with self.assertRaises(ImproperlyConfigured):
                _ = PrivateBookStorage().location

    def test_all_public_roots_reject_overlap_in_both_directions(self):
        base = Path(self.tmp.name)
        public = base / 'served'
        for setting in ('MEDIA_ROOT', 'STATIC_ROOT', 'STATICFILES_DIRS', 'prefixed-static'):
            for private in (public, public / 'private', base):
                with self.subTest(setting=setting, private=str(private)):
                    values = dict(MEDIA_ROOT=base / 'media', STATIC_ROOT=base / 'collected', STATICFILES_DIRS=[], BOOK_PRIVATE_ROOT=private)
                    if setting == 'prefixed-static':
                        values['STATICFILES_DIRS'] = [('assets', public)]
                    else:
                        values[setting] = [public] if setting == 'STATICFILES_DIRS' else public
                    with override_settings(**values):
                        self.assertTrue(check_book_storage(None))
                        with self.assertRaises(ImproperlyConfigured):
                            _ = PrivateBookStorage().location

    def test_private_root_uses_canonical_paths_and_allows_prefix_siblings(self):
        base = Path(self.tmp.name)
        with override_settings(STATIC_ROOT=base / 'assets', STATICFILES_DIRS=[],
                               BOOK_PRIVATE_ROOT=base / 'assets' / '..' / 'assets' / 'books'):
            self.assertTrue(check_book_storage(None))
        with override_settings(STATIC_ROOT=base / 'assets', STATICFILES_DIRS=[], BOOK_PRIVATE_ROOT=base / 'assets-private'):
            self.assertEqual(check_book_storage(None), [])
            self.assertEqual(Path(PrivateBookStorage().location), (base / 'assets-private').resolve())

    def test_private_root_rejects_invalid_or_file_paths(self):
        existing_file = Path(self.tmp.name) / 'not-a-directory'
        existing_file.write_text('fixture', encoding='utf-8')
        for value in ('', None, 'invalid\x00path', existing_file):
            with self.subTest(value=repr(value)), override_settings(BOOK_PRIVATE_ROOT=value):
                self.assertTrue(check_book_storage(None))
                with self.assertRaises(ImproperlyConfigured):
                    _ = PrivateBookStorage().location

    def test_unauthenticated_api_denied(self):
        book = self.book(is_published=True)
        self.api.force_authenticate(None)
        for url in [self.list_url, self.detail(book), self.content(book)]:
            self.assertEqual(self.api.get(url).status_code, 401)
        self.assertEqual(self.upload().status_code, 401)

    def test_unverified_email_jwt_denied(self):
        self.owner.email_verified = False
        self.owner.save(update_fields=['email_verified'])
        token = RefreshToken.for_user(self.owner).access_token
        self.api.force_authenticate(None)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(self.api.get(self.list_url).status_code, 401)

    def test_create_permissions(self):
        for user, expected in [(self.student, 403), (self.unverified, 403), (self.admin, 201), (self.owner, 201)]:
            self.api.force_authenticate(user)
            response = self.upload()
            self.assertEqual(response.status_code, expected, response.data)

    def test_ownership_and_uploader_cannot_be_spoofed(self):
        response = self.upload(uploaded_by=self.other.pk)
        self.assertEqual(response.status_code, 201)
        book = EBook.objects.get(pk=response.data['id'])
        self.assertEqual(book.uploaded_by, self.owner)
        book.is_published = True
        book.save()
        self.api.force_authenticate(self.other)
        self.assertEqual(self.api.patch(self.detail(book), {'title': 'Stolen'}, format='json').status_code, 403)
        self.assertEqual(self.api.delete(self.detail(book)).status_code, 403)
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.api.patch(self.detail(book), {'title': 'Admin edit'}, format='json').status_code, 200)

    def test_draft_visibility(self):
        book = self.book()
        for user, visible in [(self.owner, True), (self.admin, True), (self.other, False), (self.student, False)]:
            self.api.force_authenticate(user)
            self.assertEqual(self.api.get(self.detail(book)).status_code, 200 if visible else 404)
            self.assertEqual(bool(self.api.get(self.list_url).data), visible)

    def test_publish_unpublish_timestamps_and_visibility(self):
        book = self.book()
        self.assertIsNone(book.published_at)
        response = self.api.patch(self.detail(book), {'is_published': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.data['published_at'])
        first = response.data['published_at']
        response = self.api.patch(self.detail(book), {'title': 'Changed'}, format='json')
        self.assertEqual(response.data['published_at'], first)
        response = self.api.patch(self.detail(book), {'is_published': False}, format='json')
        self.assertIsNone(response.data['published_at'])
        self.api.force_authenticate(self.student)
        self.assertEqual(self.api.get(self.detail(book)).status_code, 404)

    def test_file_url_and_private_path_never_leak(self):
        response = self.upload(is_published='true', price='100', file_url='https://legacy.example.com/paid.pdf')
        book = EBook.objects.get(pk=response.data['id'])
        for user in [self.admin, self.owner, self.student]:
            self.api.force_authenticate(user)
            for url in [self.list_url, self.detail(book)]:
                response = self.api.get(url)
                payload = str(response.data)
                self.assertNotIn(book.source_file.name, payload)
                self.assertNotIn(book.file_url, payload)
                self.assertNotIn('source_file', payload)

    def test_authorized_download_is_attachment_without_cache(self):
        response = self.upload()
        book = EBook.objects.get(pk=response.data['id'])
        for user in [self.owner, self.admin]:
            self.api.force_authenticate(user)
            response = self.api.get(self.content(book))
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment;', response['Content-Disposition'])
            self.assertEqual(response['Cache-Control'], 'private, no-store')
            self.assertEqual(b''.join(response.streaming_content), PDF)
            response.close()
        for user in [self.other, self.student]:
            self.api.force_authenticate(user)
            self.assertEqual(self.api.get(self.content(book)).status_code, 403)

    def test_former_instructor_student_cannot_download_paid_or_unknown_drafts(self):
        books = []
        for price in (None, '100'):
            kwargs = {} if price is None else {'price': price}
            response = self.upload(**kwargs)
            self.assertEqual(response.status_code, 201, response.data)
            books.append(EBook.objects.get(pk=response.data['id']))
        self.owner.role = self.student.role
        self.owner.save(update_fields=['role'])
        # A fresh real JWT verifies the current DB role, not a force-auth fixture.
        self.api.force_authenticate(None)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.owner).access_token}')
        for book in books:
            self.assertEqual(self.api.get(self.detail(book)).status_code, 404)
            self.assertEqual(self.api.get(self.content(book)).status_code, 403)

    def test_download_permissions_for_all_prices_and_publication_states(self):
        for published in (False, True):
            for price in (None, '0', '100'):
                self.api.force_authenticate(self.owner)
                kwargs = {'is_published': str(published).lower()}
                if price is not None:
                    kwargs['price'] = price
                created = self.upload(**kwargs)
                self.assertEqual(created.status_code, 201, created.data)
                book = EBook.objects.get(pk=created.data['id'])
                for user, expected in ((self.owner, 200), (self.admin, 200), (self.other, 403), (self.student, 403), (None, 401)):
                    with self.subTest(published=published, price=price, user=getattr(user, 'pk', None)):
                        self.api.force_authenticate(user)
                        response = self.api.get(self.content(book))
                        self.assertEqual(response.status_code, expected)
                        if response.streaming:
                            self.assertEqual(b''.join(response.streaming_content), PDF)
                            response.close()

    def test_missing_private_source_does_not_redirect_to_legacy(self):
        book = self.book()
        self.assertEqual(self.api.get(self.content(book)).status_code, 404)

    def test_replacing_source_uses_new_name_and_retains_old_file(self):
        response = self.upload()
        book = EBook.objects.get(pk=response.data['id'])
        old = book.source_file.path
        response = self.api.patch(self.detail(book), {'source_file': epub()}, format='multipart')
        self.assertEqual(response.status_code, 200, response.data)
        book.refresh_from_db()
        self.assertEqual(book.file_format, 'epub')
        self.assertNotEqual(book.source_file.path, old)
        self.assertTrue(Path(old).exists())

    def test_admin_routes_require_login_and_admin(self):
        book = self.book()
        urls = [reverse('manage_books'), reverse('add_book'), reverse('edit_book', args=[book.pk]), reverse('delete_book', args=[book.pk])]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302)
            self.assertEqual(self.client.post(url, {}).status_code, 302)
        for user in [self.owner, self.student]:
            self.client.force_login(user)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.admin_payload()).status_code, 403)

    def test_admin_create_edit_replace_and_unpublish(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse('add_book'), self.admin_payload(is_published='on'))
        self.assertEqual(response.status_code, 302)
        book = EBook.objects.get(title='Dashboard book')
        self.assertEqual(book.uploaded_by, self.admin)
        self.assertTrue(book.is_published)
        self.assertIsNotNone(book.published_at)
        response = self.client.get(reverse('edit_book', args=[book.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, book.source_file.name)
        response = self.client.post(reverse('edit_book', args=[book.pk]), self.admin_payload(title='Edited', source_file=epub(), cover_image=cover()))
        self.assertEqual(response.status_code, 302)
        book.refresh_from_db()
        self.assertEqual(book.file_format, 'epub')
        self.assertFalse(book.is_published)
        self.assertIsNone(book.published_at)
        self.assertTrue(book.cover_image)

    def test_admin_invalid_upload_and_price_rejected(self):
        self.client.force_login(self.admin)
        for kwargs in [{'price': '-1'}, {'source_file': pdf(body=b'fake')}, {'highlights': '{"bad": 1}'}, {'highlights': '{}'}]:
            response = self.client.post(reverse('add_book'), self.admin_payload(**kwargs))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertFalse(EBook.objects.exists())

    def test_admin_legacy_metadata_edit_retains_url_and_unknown_price(self):
        book = self.book(is_published=True)
        self.client.force_login(self.admin)
        response = self.client.post(reverse('edit_book', args=[book.pk]), {
            'title': 'Legacy edited', 'file_url': book.file_url, 'currency': 'NPR', 'highlights': '[]', 'is_published': 'on'})
        self.assertEqual(response.status_code, 302)
        book.refresh_from_db()
        self.assertIsNone(book.price)
        self.assertTrue(book.is_published)
        self.assertEqual(book.file_url, 'https://legacy.example.com/paid.pdf')

    def test_admin_search_filter_and_shared_navigation(self):
        self.book(title='Find me', category='Science', is_published=True)
        self.book(title='Other')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('manage_books'), {'q': 'Find', 'category': 'Science', 'status': 'published'})
        self.assertContains(response, 'Find me')
        self.assertNotContains(response, 'Legacy book')
        self.assertEqual(response.context['page'].paginator.count, 1)
        self.assertContains(response, '<option value="published" selected>Published</option>', html=True)
        self.assertContains(response, '<option value="">All</option>', html=True)

        response = self.client.get(reverse('manage_books'), {'status': 'draft'})
        self.assertContains(response, '<option value="draft" selected>Draft</option>', html=True)
        self.assertEqual(response.context['page'].paginator.count, 1)
        self.assertContains(response, 'Other')
        self.assertContains(self.client.get(reverse('dashboard')), reverse('manage_books'))

    def test_admin_deletion_requires_confirmation_and_retains_files(self):
        response = self.upload()
        book = EBook.objects.get(pk=response.data['id'])
        path = book.source_file.path
        url = reverse('delete_book', args=[book.pk])
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {})
        self.assertTrue(EBook.objects.filter(pk=book.pk).exists())
        self.assertEqual(self.client.post(url, {'confirm': book.pk}).status_code, 302)
        self.assertFalse(EBook.objects.filter(pk=book.pk).exists())
        self.assertTrue(Path(path).exists())

    def test_dashboard_writes_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse('add_book'), self.admin_payload()).status_code, 403)


class DockerBookBuildContextTests(SimpleTestCase):
    """Representative exclusion contracts; a Docker engine build is separate QA."""
    def excluded(self, relative_name):
        from django.conf import settings
        patterns = [line.strip().rstrip('/') for line in (settings.BASE_DIR / '.dockerignore').read_text(encoding='utf-8').splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
        self.assertFalse(any(pattern.startswith('!') for pattern in patterns), 'Revisit context checks when adding negation rules.')
        parts = relative_name.split('/')
        # Positive patterns used here need only ancestor matching and the optional
        # leading **/. Do not read any actual credentials or uploaded content.
        candidates = ['/'.join(parts[:i]) for i in range(1, len(parts) + 1)]

        def matches(candidate, pattern):
            components, globs = candidate.split('/'), pattern.split('/')
            if globs[0] == '**':
                globs = globs[1:]
                if len(components) < len(globs):
                    return False
                components = components[-len(globs):]
            return len(components) == len(globs) and all(fnmatchcase(part, glob) for part, glob in zip(components, globs))

        return any(matches(candidate, pattern) for candidate in candidates for pattern in patterns)

    def test_sensitive_and_runtime_context_fixtures_excluded(self):
        for name in ('.env', '.env.production', 'nested/.env.local', 'private-books/content/id.pdf',
                     'private-books/backups/db.sqlite3', 'nested/private-books/book.epub',
                     'db.sqlite3', 'db.sqlite3-wal', 'db.sqlite3.backup', 'backup.sqlite3.bak',
                     'nested/local.sqlite3', 'nested/db.sqlite-journal', 'backups/database.sql',
                     'media/book-covers/id.png', 'uploads/book.epub', '.git/config',
                     'core/__pycache__/models.pyc', '.venv/Scripts/python.exe', 'venv/lib/package.py',
                     '.aws/credentials', '.ssh/id_rsa', 'secrets/token.txt', 'keys/private.pem',
                     'tmp/request.txt', 'nested/scratch.tmp'):
            with self.subTest(path=name):
                self.assertTrue(self.excluded(name), name)

    def test_required_application_context_fixtures_preserved(self):
        for name in ('manage.py', 'requirements.txt', 'Dockerfile', 'core/models.py', 'core/book_files.py',
                     'core/migrations/0053_ebook_phase1.py', 'config/settings.py',
                     'templates/admin/book_form.html', 'static/css/admin.css', 'static/images/cover.png'):
            with self.subTest(path=name):
                self.assertFalse(self.excluded(name), name)


class BookMigrationCompatibilityTests(TransactionTestCase):
    def test_real_migration_preserves_legacy_records_without_free_entitlement(self):
        previous = [('core', '0052_seed_premium_categories')]
        target = [('core', '0053_ebook_phase1')]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            role, _ = apps.get_model('core', 'Role').objects.get_or_create(name='super_admin')
            user = apps.get_model('core', 'User').objects.create(email='migration-book@example.com', name='Legacy owner', role_id=role.pk)
            old = apps.get_model('core', 'EBook').objects.create(title='Keep me', author='Legacy author',
                uploaded_by_id=user.pk, file_url='https://legacy.example.com/paid.pdf',
                cover_url='https://legacy.example.com/cover.png', is_published=True)
            draft = apps.get_model('core', 'EBook').objects.create(title='Keep draft', uploaded_by_id=user.pk,
                file_url='https://legacy.example.com/draft.epub', is_published=False)
            executor = MigrationExecutor(connection)
            executor.migrate(target)
            new_apps = executor.loader.project_state(target).apps
            model = new_apps.get_model('core', 'EBook')
            book = model.objects.get(pk=old.pk)
            self.assertEqual(book.title, old.title)
            self.assertEqual(book.file_url, old.file_url)
            self.assertEqual(book.cover_url, old.cover_url)
            self.assertEqual(book.uploaded_by_id, old.uploaded_by_id)
            self.assertEqual(book.created_at, old.created_at)
            self.assertEqual(book.updated_at, old.updated_at)
            self.assertTrue(book.is_published)
            self.assertEqual(book.published_at, old.created_at)
            self.assertIsNone(book.price)
            self.assertEqual(book.currency, 'NPR')
            self.assertEqual(book.highlights, [])
            self.assertFalse(book.source_file)
            self.assertFalse(model.objects.get(pk=draft.pk).is_published)
            self.assertIsNone(model.objects.get(pk=draft.pk).published_at)
        finally:
            MigrationExecutor(connection).migrate(latest)


def reader_epub(order=('b', 'a'), body_a=None):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('mimetype', b'application/epub+zip')
        archive.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
        archive.writestr('OPS/book.opf', '<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/></manifest><spine>' + ''.join(f'<itemref idref="{item}"/>' for item in order) + '</spine></package>')
        archive.writestr('OPS/a.xhtml', body_a or '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Alpha</h1><p>Readable A.</p></body></html>')
        archive.writestr('OPS/b.xhtml', '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Beta</h1><p>Readable B.</p></body></html>')
    return SimpleUploadedFile('reader.epub', stream.getvalue())


def reader_pdf(text=False):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    if text:
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        content = DecodedStreamObject()
        content.set_data(b'BT /F1 12 Tf 10 100 Td (Reliable chapter text.) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(content)
    stream = BytesIO()
    writer.write(stream)
    return pdf(body=stream.getvalue())


@override_settings(STORAGES=TEST_STORAGES)
class BookReaderPhase2Tests(TestCase):
    user = classmethod(BookSectionTests.user.__func__)
    setUpTestData = classmethod(BookSectionTests.setUpTestData.__func__)
    setUp = BookSectionTests.setUp
    book = BookSectionTests.book
    upload = BookSectionTests.upload
    detail = BookSectionTests.detail
    content = BookSectionTests.content

    def chapters(self, book):
        return reverse('api-book-chapters', args=[book.pk])

    def chapter_url(self, book, chapter):
        return reverse('api-book-chapter', args=[book.pk, chapter.pk])

    def chapter(self, book, number=1, **kwargs):
        from .models import BookChapter
        return BookChapter.objects.create(book=book, chapter_number=number, title=f'Chapter {number}', content='First paragraph.\n\nSecond paragraph.', **kwargs)

    def endpoint(self, name, book):
        return reverse(name, args=[book.pk])

    def imported_book(self, **kwargs):
        response = self.upload(source_file=reader_epub(**kwargs))
        self.assertEqual(response.status_code, 201, response.data)
        return EBook.objects.get(pk=response.data['id'])

    def import_book(self, book, mode='create'):
        return self.api.post(self.endpoint('api-book-import', book), {'mode': mode}, format='json')

    def test_order_contents_navigation_and_no_list_content(self):
        book = self.book()
        last = self.chapter(book, 3)
        first = self.chapter(book, 1)
        middle = self.chapter(book, 2)
        response = self.api.get(self.chapters(book))
        self.assertEqual(response.status_code, 200)
        self.assertEqual([c['id'] for c in response.data['chapters']], [first.pk, middle.pk, last.pk])
        self.assertNotIn('content', response.data['chapters'][0])
        response = self.api.get(self.chapter_url(book, middle))
        self.assertEqual(response.data['previous_chapter_id'], first.pk)
        self.assertEqual(response.data['next_chapter_id'], last.pk)
        self.assertEqual(response.data['chapter']['content_format'], 'text')
        self.assertIsNone(self.api.get(self.chapter_url(book, first)).data['previous_chapter_id'])
        self.assertIsNone(self.api.get(self.chapter_url(book, last)).data['next_chapter_id'])

    def test_pause_prompt_is_optional_plain_text(self):
        book = self.book()
        chapter = self.chapter(book)
        self.assertEqual(self.api.get(self.chapter_url(book, chapter)).data['chapter']['pause_prompt'], '')
        response = self.api.patch(self.chapter_url(book, chapter),
                                  {'pause_prompt': 'Which <b>example</b>\r\nwould you try?\x07'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.api.get(self.chapter_url(book, chapter)).data['chapter']['pause_prompt'],
                         'Which <b>example</b>\nwould you try?')
        self.assertEqual(self.api.patch(self.chapter_url(book, chapter), {'pause_prompt': 'x' * 2001}, format='json').status_code, 400)
        # The contents list stays light, like `content`.
        self.assertNotIn('pause_prompt', self.api.get(self.chapters(book)).data['chapters'][0])
        self.client.force_login(self.admin)
        response = self.client.post(reverse('edit_book_chapter', args=[book.pk, chapter.pk]), {
            'chapter_number': 1, 'title': 'Chapter 1', 'content': chapter.content, 'pause_prompt': 'What surprised you?'})
        self.assertEqual(response.status_code, 302)
        chapter.refresh_from_db()
        self.assertEqual(chapter.pause_prompt, 'What surprised you?')

    def test_unique_order_and_reorder_keeps_ids(self):
        book = self.book()
        first, second = self.chapter(book), self.chapter(book, 2)
        response = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Duplicate'}, format='json')
        self.assertEqual(response.status_code, 400)
        url = self.endpoint('api-book-reorder', book)
        for ids in ([first.pk], [first.pk, first.pk], [first.pk, 99999]):
            self.assertEqual(self.api.post(url, {'chapter_ids': ids}, format='json').status_code, 400)
        response = self.api.post(url, {'chapter_ids': [second.pk, first.pk]}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(book.chapters.values_list('pk', flat=True)), [second.pk, first.pk])

    def test_chapter_cross_book_ids_rejected(self):
        book, other = self.book(), self.book(title='Other')
        chapter = self.chapter(other)
        self.assertEqual(self.api.get(self.chapter_url(book, chapter)).status_code, 404)
        self.assertEqual(self.api.patch(self.chapter_url(book, chapter), {'title': 'Wrong'}, format='json').status_code, 404)
        self.assertEqual(self.api.delete(self.chapter_url(book, chapter)).status_code, 404)

    def test_manual_authoring_is_literal_text_and_admin_preview_is_escaped(self):
        book = self.book()
        content = '<script>evil()</script><p onclick="evil()">Hello <a href="javascript:evil()">link</a></p><iframe>bad</iframe>'
        response = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': '<b>Safe</b>',
            'content': content}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['title'], '<b>Safe</b>')
        self.assertEqual(response.data['content'], content)
        self.assertEqual(response.data['content_format'], 'text')
        self.assertGreater(response.data['estimated_reading_minutes'], 0)
        self.client.force_login(self.admin)
        preview = self.client.get(reverse('edit_book_chapter', args=[book.pk, response.data['id']]))
        self.assertNotContains(preview, '<script>evil()</script>')
        self.assertContains(preview, '&lt;script&gt;evil()&lt;/script&gt;')

    def test_epub_spine_order_and_hidden_internal_references(self):
        book = self.imported_book()
        response = self.import_book(book)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['created'], 2)
        chapters = list(book.chapters.all())
        self.assertEqual([c.title for c in chapters], ['Beta', 'Alpha'])
        payload = str(self.api.get(self.chapter_url(book, chapters[0])).data)
        for secret in ('OPS/', book.source_file.name, 'source_reference', 'imported_digest'):
            self.assertNotIn(secret, payload)

    def test_epub_scripts_events_links_and_foreign_content_removed(self):
        body = '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Safe<script>badtitle()</script></h1><script>badscript()</script><p onload="event()">Read <a href="javascript:danger()">this</a></p><svg><script>svgscript()</script></svg><style>badcss</style><img src="https://remote.invalid/track"/></body></html>'
        book = self.imported_book(body_a=body)
        self.assertEqual(self.import_book(book).status_code, 200)
        chapter = book.chapters.get(source_reference='OPS/a.xhtml')
        self.assertEqual(chapter.title, 'Safe')
        for unsafe in ('badtitle', 'badscript', 'event()', 'javascript:', 'svgscript', 'badcss', 'remote.invalid', '<'):
            self.assertNotIn(unsafe, chapter.content)
        self.assertIn('Read this', chapter.content)

    def test_malformed_epub_is_atomic(self):
        book = self.imported_book(body_a='<html>not closed')
        response = self.import_book(book)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['code'], 'INVALID_EPUB')
        self.assertFalse(book.chapters.exists())

    def test_epub_missing_or_repeated_spine_is_rejected(self):
        for order in ((), ('a', 'a'), ('missing',)):
            book = self.imported_book(order=order)
            self.assertEqual(self.import_book(book).status_code, 400)
            self.assertFalse(book.chapters.exists())

    def test_epub_dtd_and_entity_rejected_at_import(self):
        book = self.imported_book(body_a='<!DOCTYPE html [<!ENTITY x "unsafe">]><html xmlns="http://www.w3.org/1999/xhtml"><body>&x;</body></html>')
        self.assertEqual(self.import_book(book).status_code, 400)
        self.assertFalse(book.chapters.exists())

    def test_reimport_requires_confirmation_and_preserves_ids(self):
        book = self.imported_book()
        first = self.import_book(book)
        ids = first.data['chapter_ids']
        self.assertEqual(self.import_book(book).status_code, 409)
        response = self.import_book(book, 'refresh')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['chapter_ids'], ids)
        self.assertEqual(book.chapters.count(), 2)

    def test_reimport_refuses_manual_edits_and_manually_authored_chapters(self):
        book = self.imported_book()
        self.import_book(book)
        chapter = book.chapters.first()
        self.api.patch(self.chapter_url(book, chapter), {'content': 'My edited text'}, format='json')
        response = self.import_book(book, 'refresh')
        self.assertEqual(response.status_code, 409)
        chapter.refresh_from_db()
        self.assertEqual(chapter.content, 'My edited text')
        book = self.imported_book()
        self.chapter(book)
        self.assertEqual(self.import_book(book, 'refresh').status_code, 409)
        self.assertEqual(book.chapters.count(), 1)

    def test_refresh_updates_spine_order_without_resetting_reader_state(self):
        book = self.imported_book()
        self.import_book(book)
        chapter = book.chapters.first()
        self.api.put(self.endpoint('api-book-progress', book), {'chapter_id': chapter.pk, 'position': {'paragraph': 1}, 'completed': True}, format='json')
        self.api.post(self.endpoint('api-book-bookmarks', book), {'chapter_id': chapter.pk, 'anchor': 'saved'}, format='json')
        self.api.patch(self.detail(book), {'source_file': reader_epub(order=('a', 'b'))}, format='multipart')
        book.refresh_from_db()
        self.assertEqual(self.import_book(book, 'refresh').status_code, 200)
        self.assertEqual(book.chapters.last().pk, chapter.pk)
        progress = self.api.get(self.endpoint('api-book-progress', book)).data
        self.assertEqual(progress['completed_chapter_ids'], [chapter.pk])
        self.assertEqual(progress['position'], {'paragraph': 1})
        self.assertEqual(len(self.api.get(self.endpoint('api-book-bookmarks', book)).data), 1)

    def test_all_book_reader_actions_deny_consumers_and_role_changes(self):
        book = self.imported_book()
        self.import_book(book)
        chapter = book.chapters.first()
        book.is_published = True
        book.price = Decimal('100')
        book.save()
        actions = [('get', self.chapters(book), {}), ('post', self.chapters(book), {'chapter_number': 4, 'title': 'bad'}),
            ('get', self.chapter_url(book, chapter), {}), ('patch', self.chapter_url(book, chapter), {'content': 'bad'}),
            ('delete', self.chapter_url(book, chapter), {}), ('get', self.content(book), {}),
            ('get', self.endpoint('api-book-progress', book), {}),
            ('put', self.endpoint('api-book-progress', book), {'chapter_id': chapter.pk}),
            ('get', self.endpoint('api-book-bookmarks', book), {}),
            ('post', self.endpoint('api-book-bookmarks', book), {'chapter_id': chapter.pk}),
            ('post', self.endpoint('api-book-import', book), {}),
            ('post', self.endpoint('api-book-reorder', book), {'chapter_ids': [chapter.pk]})]
        for user in (self.student, self.other, None):
            self.api.force_authenticate(user)
            for method, url, data in actions:
                with self.subTest(user=getattr(user, 'pk', None), method=method, url=url):
                    response = getattr(self.api, method)(url, data, format='json')
                    self.assertEqual(response.status_code, 401 if user is None else 403)
        self.owner.role = self.student.role
        self.owner.save(update_fields=['role'])
        self.api.force_authenticate(None)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.owner).access_token}')
        for method, url, data in actions:
            self.assertEqual(getattr(self.api, method)(url, data, format='json').status_code, 403)

    def test_zero_and_unknown_price_do_not_grant_reader_access(self):
        for price in (None, Decimal('0')):
            book = self.book(is_published=True, price=price)
            self.chapter(book)
            self.api.force_authenticate(self.student)
            self.assertEqual(self.api.get(self.chapters(book)).status_code, 403)

    def test_progress_create_resume_completion_and_reopen(self):
        book = self.book()
        chapter = self.chapter(book)
        other = self.chapter(book, 2)
        url = self.endpoint('api-book-progress', book)
        self.assertIsNone(self.api.get(url).data['last_read_at'])
        response = self.api.put(url, {'chapter_id': chapter.pk, 'position': {'paragraph': 1, 'offset': 2}, 'completed': True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['overall_percentage'], 50)
        self.assertEqual(self.api.get(url).data['position']['offset'], 2)
        self.api.patch(self.chapter_url(book, chapter), {'title': 'Ordinary edit'}, format='json')
        self.assertEqual(self.api.get(url).data['completed_chapter_ids'], [chapter.pk])
        self.api.put(url, {'chapter_id': other.pk, 'completed': True}, format='json')
        self.assertEqual(self.api.get(url).data['overall_percentage'], 100)
        self.api.put(url, {'chapter_id': chapter.pk, 'position': {}}, format='json')
        self.assertEqual(self.api.get(url).data['overall_percentage'], 100)
        self.api.put(url, {'chapter_id': chapter.pk, 'completed': False}, format='json')
        self.assertEqual(self.api.get(url).data['overall_percentage'], 50)

    def test_progress_rejects_cross_book_positions_and_forged_totals(self):
        book = self.book()
        chapter = self.chapter(book)
        other = self.chapter(self.book())
        url = self.endpoint('api-book-progress', book)
        for payload in ({'chapter_id': other.pk}, {'chapter_id': chapter.pk, 'overall_percentage': 100},
                        {'chapter_id': chapter.pk, 'position': {'paragraph': -1}},
                        {'chapter_id': chapter.pk, 'position': {'offset': True}},
                        {'chapter_id': chapter.pk, 'position': {'paragraph': 999}},
                        {'chapter_id': chapter.pk, 'position': {'url': 'private'}}, {'chapter_id': None}):
            self.assertEqual(self.api.put(url, payload, format='json').status_code, 400)

    def test_progress_isolation_and_continue_reading(self):
        book = self.book()
        chapter = self.chapter(book)
        self.api.put(self.endpoint('api-book-progress', book), {'chapter_id': chapter.pk, 'completed': True}, format='json')
        self.assertEqual(len(self.api.get(reverse('api-reader-continue')).data['books']), 1)
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.api.get(self.endpoint('api-book-progress', book)).data['overall_percentage'], 0)
        self.assertEqual(self.api.get(reverse('api-reader-continue')).data['books'], [])
        self.api.force_authenticate(self.student)
        self.assertEqual(self.api.get(reverse('api-reader-continue')).status_code, 403)

    def test_bookmark_idempotence_ownership_and_cross_book_protection(self):
        book = self.book()
        chapter = self.chapter(book)
        url = self.endpoint('api-book-bookmarks', book)
        payload = {'chapter_id': chapter.pk, 'anchor': 'p-1', 'note': '<script>bad</script>Remember'}
        first = self.api.post(url, payload, format='json')
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data['note'], 'Remember')
        self.assertEqual(self.api.post(url, {**payload, 'position': {'paragraph': 1}}, format='json').data['id'], first.data['id'])
        delete = reverse('api-book-bookmark', args=[book.pk, first.data['id']])
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.api.get(url).data, [])
        self.assertEqual(self.api.delete(delete).status_code, 404)
        self.api.force_authenticate(self.owner)
        other = self.book()
        self.assertEqual(self.api.post(self.endpoint('api-book-bookmarks', other), payload, format='json').status_code, 400)
        self.assertEqual(self.api.delete(reverse('api-book-bookmark', args=[other.pk, first.data['id']])).status_code, 404)
        self.assertEqual(self.api.delete(delete).status_code, 204)
        self.assertEqual(self.api.get(url).data, [])

    def test_bookmark_position_normalization_and_invalid_anchors(self):
        book = self.book()
        chapter = self.chapter(book)
        url = self.endpoint('api-book-bookmarks', book)
        first = self.api.post(url, {'chapter_id': chapter.pk}, format='json')
        second = self.api.post(url, {'chapter_id': chapter.pk, 'position': {'offset': 0, 'paragraph': 0}}, format='json')
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.api.post(url, {'chapter_id': chapter.pk, 'anchor': '<script>'}, format='json').status_code, 400)

    def test_settings_defaults_validation_and_isolation(self):
        url = reverse('api-reader-settings')
        self.assertEqual(self.api.get(url).data['font_size'], 18)
        response = self.api.patch(url, {'theme': 'sepia', 'font_family': 'serif', 'font_size': 24, 'line_spacing': '2.0'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.api.get(url).data['theme'], 'sepia')
        for value in ({'font_size': 11}, {'font_size': 33}, {'font_family': 'javascript'}, {'theme': 'neon'}, {'line_spacing': '2.6'}, {'line_spacing': '0.9'}, {'brightness': 0}, {'user': self.admin.pk}):
            self.assertEqual(self.api.patch(url, value, format='json').status_code, 400)
        self.api.force_authenticate(self.admin)
        self.assertEqual(self.api.get(url).data['theme'], 'light')
        self.api.force_authenticate(None)
        self.assertEqual(self.api.get(url).status_code, 401)

    def test_chapter_deletion_clears_orphan_resume_and_related_state(self):
        book = self.book()
        chapter = self.chapter(book)
        self.api.put(self.endpoint('api-book-progress', book), {'chapter_id': chapter.pk, 'position': {'paragraph': 1}, 'completed': True}, format='json')
        self.api.post(self.endpoint('api-book-bookmarks', book), {'chapter_id': chapter.pk}, format='json')
        self.assertEqual(self.api.delete(self.chapter_url(book, chapter)).status_code, 204)
        progress = self.api.get(self.endpoint('api-book-progress', book)).data
        self.assertIsNone(progress['last_chapter_id'])
        self.assertEqual(progress['position'], {})
        self.assertEqual(progress['completed_chapter_ids'], [])
        self.assertEqual(self.api.get(self.endpoint('api-book-bookmarks', book)).data, [])

    def test_malformed_json_and_offset_requests_rejected(self):
        book = self.book()
        chapter = self.chapter(book)
        self.assertEqual(self.api.post(self.chapters(book), [{}], format='json').status_code, 400)
        self.assertEqual(self.api.patch(reverse('api-reader-settings'), [], format='json').status_code, 400)
        self.assertEqual(self.api.put(self.endpoint('api-book-progress', book), {'chapter_id': chapter.pk, 'position': {'paragraph': 0, 'offset': 9999}}, format='json').status_code, 400)

    def test_pdf_fallback_ranges_and_protected_delivery(self):
        created = self.upload(source_file=reader_pdf())
        book = EBook.objects.get(pk=created.data['id'])
        self.assertEqual(self.api.get(self.chapters(book)).data['reader_mode'], 'protected_pdf')
        self.assertEqual(book.chapters.count(), 0)
        for fields in ({'pdf_page_start': 2, 'pdf_page_end': 1}, {'pdf_page_start': 1}, {'pdf_page_start': 0, 'pdf_page_end': 2}):
            response = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Range', **fields}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        response = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Selected pages', 'pdf_page_start': 1, 'pdf_page_end': 1}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        chapter = book.chapters.get()
        extract = reverse('api-book-pdf-extract', args=[book.pk, chapter.pk])
        self.assertEqual(self.api.post(extract, {}, format='json').status_code, 400)
        chapter.refresh_from_db()
        self.assertEqual(chapter.content, '')
        self.api.force_authenticate(self.student)
        self.assertEqual(self.api.post(extract, {}, format='json').status_code, 403)
        self.assertEqual(self.api.get(self.content(book)).status_code, 403)

    def test_explicit_pdf_text_extraction_and_no_overwrite(self):
        created = self.upload(source_file=reader_pdf(text=True))
        book = EBook.objects.get(pk=created.data['id'])
        chapter = self.chapter(book, pdf_page_start=1, pdf_page_end=1)
        chapter.content = ''
        chapter.save()
        url = reverse('api-book-pdf-extract', args=[book.pk, chapter.pk])
        response = self.api.post(url, {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('Reliable chapter text.', response.data['content'])
        self.assertEqual(self.api.post(url, {}, format='json').status_code, 409)

    def test_pdf_range_invalid_for_epub_and_pdf_positions_validated(self):
        book = self.imported_book()
        self.assertEqual(self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Bad', 'pdf_page_start': 1, 'pdf_page_end': 2}, format='json').status_code, 400)
        book = EBook.objects.get(pk=self.upload(source_file=reader_pdf()).data['id'])
        url = self.endpoint('api-book-progress', book)
        self.assertEqual(self.api.put(url, {'chapter_id': None, 'position': {'page': 1}}, format='json').status_code, 200)
        chapter = self.chapter(book, pdf_page_start=1, pdf_page_end=1)
        self.assertEqual(self.api.put(url, {'chapter_id': chapter.pk, 'position': {'page': 2}}, format='json').status_code, 400)

    def test_admin_chapter_crud_preview_and_confirmation(self):
        self.client.force_login(self.admin)
        book = self.book()
        url = reverse('manage_book_chapters', args=[book.pk])
        response = self.client.post(url, {'chapter_number': 1, 'title': 'Manual', 'content': '<b>Plain</b><script>bad()</script>'})
        self.assertEqual(response.status_code, 302)
        chapter = book.chapters.get()
        self.assertEqual(chapter.content, '<b>Plain</b><script>bad()</script>')
        edit = reverse('edit_book_chapter', args=[book.pk, chapter.pk])
        self.assertContains(self.client.get(edit), 'Plain-text preview')
        self.assertEqual(self.client.post(edit, {'chapter_number': 1, 'title': 'Edited', 'content': 'Updated'}).status_code, 302)
        delete = reverse('delete_book_chapter', args=[book.pk, chapter.pk])
        self.client.get(delete)
        self.client.post(delete, {})
        self.assertTrue(book.chapters.exists())
        self.assertEqual(self.client.post(delete, {'confirm': chapter.pk}).status_code, 302)
        self.assertFalse(book.chapters.exists())

    def test_admin_import_review_reorder_and_authorization(self):
        book = self.imported_book()
        url = reverse('manage_book_chapters', args=[book.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(url, {'action': 'import'}).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.post(url, {'action': 'import', 'mode': 'create'}, follow=True)
        self.assertContains(response, '2 created')
        ids = list(book.chapters.values_list('pk', flat=True))
        self.assertEqual(self.client.post(url, {'action': 'reorder', 'chapter_ids': ','.join(map(str, reversed(ids)))}).status_code, 302)
        self.assertEqual(list(book.chapters.values_list('pk', flat=True)), list(reversed(ids)))
        chapter = book.chapters.first()
        for name in ('edit_book_chapter', 'delete_book_chapter'):
            self.client.force_login(self.student)
            self.assertEqual(self.client.get(reverse(name, args=[book.pk, chapter.pk])).status_code, 403)

    def test_admin_chapter_forms_enforce_csrf(self):
        book = self.book()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse('manage_book_chapters', args=[book.pk]), {'title': 'bad'}).status_code, 403)

    def test_audit_former_student_legacy_book_mutations(self):
        created = self.upload(source_file=reader_pdf(), is_published='true', price='100')
        book = EBook.objects.get(pk=created.data['id'])
        chapter = self.chapter(book)
        before = EBook.objects.values().get(pk=book.pk)
        files = sorted(str(path) for path in (Path(self.tmp.name) / 'private').rglob('*') if path.is_file())
        self.owner.role = self.student.role
        self.owner.save(update_fields=['role'])
        self.api.force_authenticate(None)
        self.api.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(self.owner).access_token}')
        self.assertEqual(self.api.delete(self.chapter_url(book, chapter)).status_code, 403)
        for method in ('put', 'patch', 'delete'):
            with self.subTest(method=method):
                payload = {'title': 'Forbidden', 'is_published': 'false', 'source_file': reader_pdf(text=True)} if method != 'delete' else {}
                response = getattr(self.api, method)(self.detail(book), payload, format='multipart')
                self.assertEqual(response.status_code, 403, getattr(response, 'data', None))
                self.assertEqual(EBook.objects.values().get(pk=book.pk), before)
                self.assertTrue(book.chapters.filter(pk=chapter.pk).exists())
                self.assertEqual(sorted(str(path) for path in (Path(self.tmp.name) / 'private').rglob('*') if path.is_file()), files)
        # Catalogue visibility is preserved for the now-student account.
        self.assertEqual(self.api.get(self.detail(book)).status_code, 200)

    def test_legacy_book_mutations_allow_current_managers(self):
        for user in (self.owner, self.admin):
            with self.subTest(user=user.pk):
                book = self.book(is_published=True)
                chapter = self.chapter(book)
                self.api.force_authenticate(user)
                payload = dict(self.api.get(self.detail(book)).data)
                payload['title'] = 'Authorized PUT'
                self.assertEqual(self.api.put(self.detail(book), payload, format='json').status_code, 200)
                response = self.api.patch(self.detail(book), {'source_file': reader_pdf(), 'is_published': True}, format='multipart')
                self.assertEqual(response.status_code, 200, response.data)
                self.assertTrue(book.chapters.filter(pk=chapter.pk).exists())
                self.assertEqual(self.api.delete(self.detail(book)).status_code, 204)
                self.assertFalse(EBook.objects.filter(pk=book.pk).exists())

    def test_nonowner_cannot_mutate_book_or_replace_source(self):
        book = self.book(is_published=True)
        chapter = self.chapter(book)
        before = EBook.objects.values().get(pk=book.pk)
        self.api.force_authenticate(self.other)
        for method in ('put', 'patch', 'delete'):
            response = getattr(self.api, method)(self.detail(book), {'title': 'No', 'source_file': reader_pdf()} if method != 'delete' else {}, format='multipart')
            self.assertEqual(response.status_code, 403)
            self.assertEqual(EBook.objects.values().get(pk=book.pk), before)
            self.assertTrue(book.chapters.filter(pk=chapter.pk).exists())
        self.assertFalse((Path(self.tmp.name) / 'private').exists())

    def test_audit_plain_text_metadata_edit(self):
        book = self.book()
        original = 'Use &lt;code&gt;literal&lt;/code&gt; here.'
        created = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Examples', 'content': original}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        chapter = book.chapters.get()
        self.assertEqual(chapter.content, original)
        before = chapter.content.encode('utf-8')
        response = self.api.patch(self.chapter_url(book, chapter), {'title': 'Renamed only'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        chapter.refresh_from_db()
        self.assertEqual(chapter.content.encode('utf-8'), before)
        for _ in range(3):
            chapter.save()
            chapter.refresh_from_db()
            self.assertEqual(chapter.content.encode('utf-8'), before)

    def test_plain_text_angles_entities_and_whitespace_are_stable(self):
        book = self.book()
        content = '  <code>literal</code> &lt;escaped&gt;\r\n\r\n\tindented  text\r\n'
        canonical = content.replace('\r\n', '\n')
        created = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Text', 'content': content}, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        chapter = book.chapters.get()
        self.assertEqual(chapter.content, canonical)
        self.assertEqual(self.api.get(self.chapter_url(book, chapter)).data['chapter']['content'], canonical)
        self.client.force_login(self.admin)
        url = reverse('edit_book_chapter', args=[book.pk, chapter.pk])
        self.assertEqual(self.client.post(url, {'chapter_number': 1, 'title': 'Admin edit', 'content': canonical}).status_code, 302)
        chapter.refresh_from_db()
        self.assertEqual(chapter.content, canonical)

    def test_audit_escaped_epub_refresh(self):
        from .book_reader import chapter_digest
        body = '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Alpha</h1><p>&amp;lt;code&amp;gt;literal&amp;lt;/code&amp;gt;</p><p>&lt;code&gt;literal&lt;/code&gt;</p></body></html>'
        book = self.imported_book(body_a=body)
        imported = self.import_book(book)
        self.assertEqual(imported.status_code, 200, imported.data)
        chapter = book.chapters.get(source_reference='OPS/a.xhtml')
        self.assertIn('&lt;code&gt;literal&lt;/code&gt;', chapter.content)
        self.assertIn('<code>literal</code>', chapter.content)
        for item in book.chapters.all():
            self.assertEqual(item.imported_digest, chapter_digest(item))
        self.assertEqual(self.import_book(book).status_code, 409)
        refreshed = self.import_book(book, 'refresh')
        self.assertEqual(refreshed.status_code, 200, refreshed.data)
        self.assertEqual(refreshed.data['chapter_ids'], imported.data['chapter_ids'])
        self.assertEqual(book.chapters.count(), 2)
        self.api.patch(self.chapter_url(book, chapter), {'content': 'Actual manual edit <code>preserved</code>'}, format='json')
        before = list(book.chapters.values())
        self.assertEqual(self.import_book(book, 'refresh').status_code, 409)
        self.assertEqual(list(book.chapters.values()), before)

    def test_refresh_failure_rolls_back_all_chapters(self):
        from unittest.mock import patch
        from .models import BookChapter
        from .book_reader import import_epub
        book = self.imported_book()
        self.assertEqual(self.import_book(book).status_code, 200)
        before = list(book.chapters.values())
        original_save = BookChapter.save
        calls = []

        def fail_second(chapter, *args, **kwargs):
            calls.append(chapter.pk)
            if len(calls) == 2:
                raise RuntimeError('Injected failure')
            return original_save(chapter, *args, **kwargs)

        with patch.object(BookChapter, 'save', fail_second), self.assertRaises(RuntimeError):
            import_epub(book, 'refresh')
        self.assertEqual(list(book.chapters.values()), before)

    def test_audit_pdf_actual_page_boundaries(self):
        from .models import BookReadingProgress
        book = EBook.objects.get(pk=self.upload(source_file=reader_pdf(text=True)).data['id'])
        invalid = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Nonexistent', 'pdf_page_start': 3, 'pdf_page_end': 3}, format='json')
        self.assertEqual(invalid.status_code, 400, invalid.data)
        self.assertFalse(book.chapters.exists())
        forged = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Forged count', 'pdf_page_start': 3,
            'pdf_page_end': 3, 'page_count': 999}, format='json')
        self.assertEqual(forged.status_code, 400)
        url = self.endpoint('api-book-progress', book)
        self.assertEqual(self.api.put(url, {'chapter_id': None, 'position': {'page': 3}}, format='json').status_code, 400)
        self.assertFalse(BookReadingProgress.objects.filter(book=book).exists())
        self.assertEqual(self.api.put(url, {'chapter_id': None, 'position': {'page': 1}}, format='json').status_code, 200)
        valid = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Valid', 'pdf_page_start': 1, 'pdf_page_end': 1}, format='json')
        self.assertEqual(valid.status_code, 201, valid.data)
        self.assertEqual(self.api.put(url, {'chapter_id': valid.data['id'], 'position': {'page': 1}}, format='json').status_code, 200)

    def test_legacy_invalid_pdf_range_cannot_validate_resume_page(self):
        book = EBook.objects.get(pk=self.upload(source_file=reader_pdf()).data['id'])
        # Simulate an old record accepted before actual page-count validation.
        chapter = self.chapter(book, pdf_page_start=3, pdf_page_end=3)
        response = self.api.put(self.endpoint('api-book-progress', book), {'chapter_id': chapter.pk, 'position': {'page': 3}}, format='json')
        self.assertEqual(response.status_code, 400, response.data)

    def test_pdf_range_validation_is_shared_with_admin(self):
        book = EBook.objects.get(pk=self.upload(source_file=reader_pdf()).data['id'])
        self.client.force_login(self.admin)
        url = reverse('manage_book_chapters', args=[book.pk])
        data = {'chapter_number': 1, 'title': 'Range', 'pdf_page_start': 3, 'pdf_page_end': 3}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(book.chapters.exists())
        data.update(pdf_page_start=1, pdf_page_end=1)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(book.chapters.get().pdf_page_end, 1)

    def test_corrupt_and_encrypted_pdf_page_operations_fail_safely(self):
        from pypdf import PdfWriter
        encrypted = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.encrypt('not-a-client-provided-parser-password')
        writer.write(encrypted)
        for source in (pdf(), pdf(body=encrypted.getvalue())):
            book = EBook.objects.get(pk=self.upload(source_file=source).data['id'])
            response = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'No', 'pdf_page_start': 1, 'pdf_page_end': 1}, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            progress = self.api.put(self.endpoint('api-book-progress', book), {'chapter_id': None, 'position': {'page': 1}}, format='json')
            self.assertEqual(progress.status_code, 400, progress.data)
            for payload in (response.data, progress.data):
                self.assertNotIn(book.source_file.name, str(payload))
                self.assertNotIn(self.tmp.name, str(payload))
            fallback = self.api.get(self.content(book))
            self.assertEqual(fallback.status_code, 200)
            list(fallback.streaming_content)
            fallback.close()

    def test_pdf_count_timeout_is_controlled_and_does_not_create_state(self):
        from unittest.mock import patch
        from subprocess import TimeoutExpired
        book = EBook.objects.get(pk=self.upload(source_file=reader_pdf()).data['id'])
        with patch('subprocess.run', side_effect=TimeoutExpired('private-command', 15)):
            response = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'No', 'pdf_page_start': 1, 'pdf_page_end': 1}, format='json')
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(book.chapters.exists())
        self.assertNotIn('private-command', str(response.data))
        recovered = self.api.post(self.chapters(book), {'chapter_number': 1, 'title': 'Recovered', 'pdf_page_start': 1, 'pdf_page_end': 1}, format='json')
        self.assertEqual(recovered.status_code, 201, recovered.data)

    def test_pdf_cross_book_references_remain_denied(self):
        book = EBook.objects.get(pk=self.upload(source_file=reader_pdf()).data['id'])
        other = EBook.objects.get(pk=self.upload(source_file=reader_pdf()).data['id'])
        chapter = self.chapter(other, pdf_page_start=1, pdf_page_end=1)
        self.assertEqual(self.api.put(self.endpoint('api-book-progress', book), {'chapter_id': chapter.pk, 'position': {'page': 1}}, format='json').status_code, 400)
        self.assertEqual(self.api.post(reverse('api-book-pdf-extract', args=[book.pk, chapter.pk]), {}, format='json').status_code, 404)

    def test_audit_admin_malformed_chapter_id(self):
        book = self.book()
        self.client.force_login(self.admin)
        self.client.raise_request_exception = False
        url = reverse('manage_book_chapters', args=[book.pk])
        response = self.client.post(url, {'action': 'extract-pdf', 'chapter_id': 'not-an-integer'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose a valid positive chapter ID.')
        self.assertNotIn(b'Traceback', response.content)

    def test_admin_extraction_id_validation_and_valid_action(self):
        book = EBook.objects.get(pk=self.upload(source_file=reader_pdf(text=True)).data['id'])
        chapter = self.chapter(book, pdf_page_start=1, pdf_page_end=1)
        chapter.content = ''
        chapter.save()
        foreign = self.chapter(self.book())
        self.client.force_login(self.admin)
        self.client.raise_request_exception = False
        url = reverse('manage_book_chapters', args=[book.pk])
        for value in (None, '', '0', '-1', '1.5', 'not-an-integer', '99999999', str(foreign.pk)):
            with self.subTest(value=value):
                payload = {'action': 'extract-pdf'}
                if value is not None:
                    payload['chapter_id'] = value
                response = self.client.post(url, payload)
                self.assertIn(response.status_code, (200, 400, 404))
                self.assertNotIn(b'Traceback', response.content)
                chapter.refresh_from_db()
                self.assertEqual(chapter.content, '')
        self.assertEqual(self.client.post(url, {'action': 'extract-pdf', 'chapter_id': chapter.pk}).status_code, 302)
        chapter.refresh_from_db()
        self.assertIn('Reliable chapter text.', chapter.content)


class BookReaderMigrationTests(TransactionTestCase):
    def test_phase2_preserves_phase1_book_and_private_reference(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = [('core', '0053_ebook_phase1')]
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            role, _ = apps.get_model('core', 'Role').objects.get_or_create(name='super_admin')
            user = apps.get_model('core', 'User').objects.create(email='phase2-migration@example.com', name='Owner', role_id=role.pk)
            book = apps.get_model('core', 'EBook').objects.create(title='Preserved private book', uploaded_by_id=user.pk,
                file_url='https://legacy.example.com/book.pdf', source_file='content/retained.pdf', file_format='pdf', price=None, is_published=True)
            reader_target = [('core', '0054_book_reader_phase2')]
            reader_executor = MigrationExecutor(connection)
            reader_executor.migrate(reader_target)
            reader_apps = reader_executor.loader.project_state(reader_target).apps
            reader_book = reader_apps.get_model('core', 'EBook').objects.get(pk=book.pk)
            self.assertEqual(reader_book.chapters.count(), 0)
            chapter = reader_apps.get_model('core', 'BookChapter').objects.create(
                book_id=book.pk, chapter_number=1, title='Preserved chapter', content='Original text.',
            )
            reader_apps.get_model('core', 'BookReadingProgress').objects.create(
                book_id=book.pk, user_id=user.pk, last_chapter_id=chapter.pk, position={'paragraph': 0},
            )
            MigrationExecutor(connection).migrate(latest)
            saved = EBook.objects.get(pk=book.pk)
            self.assertEqual(saved.source_file.name, 'content/retained.pdf')
            self.assertEqual(saved.file_url, book.file_url)
            self.assertTrue(saved.is_published)
            self.assertIsNone(saved.price)
            self.assertEqual(saved.created_at, book.created_at)
            self.assertEqual(saved.chapters.get(pk=chapter.pk).content, 'Original text.')
            self.assertEqual(saved.reading_progress.get(user_id=user.pk).position, {'paragraph': 0})
            self.assertFalse(saved.entitlements.exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
