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
        executor.migrate(previous)
        try:
            apps = executor.loader.project_state(previous).apps
            role = apps.get_model('core', 'Role').objects.get(name='super_admin')
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
            MigrationExecutor(connection).migrate(target)
