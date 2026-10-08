import io
import shutil
import tempfile
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from .documents import MAX_CERTIFICATE_FILES, media_src
from .models import InstructorProfile, Role, StudentProfile, User, VerificationDocument

MEDIA_ROOT = tempfile.mkdtemp()


def png(name='photo.png'):
	buffer = io.BytesIO()
	Image.new('RGB', (8, 8), 'teal').save(buffer, format='PNG')
	return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


def pdf(name='doc.pdf', body=b'%PDF-1.4 test'):
	return SimpleUploadedFile(name, body, content_type='application/pdf')


def docx(name='cv.docx'):
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, 'w') as archive:
		archive.writestr('word/document.xml', '<w:document/>')
	return SimpleUploadedFile(
		name, buffer.getvalue(),
		content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
	)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class MediaUploadTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

	def setUp(self):
		self.client = APIClient()
		self.student = User.objects.create_user(
			email='media-student@example.com', password='A-strong-password-123',
			name='Student', role=Role.objects.get(name='student'),
		)
		StudentProfile.objects.create(user=self.student)
		self.instructor = User.objects.create_user(
			email='media-instructor@example.com', password='A-strong-password-123',
			name='Instructor', role=Role.objects.get(name='instructor'),
		)
		InstructorProfile.objects.create(user=self.instructor)

	def patch_me(self, user, data):
		self.client.force_authenticate(user)
		return self.client.patch('/api/v1/me/', data, format='multipart')

	def test_html_disguised_as_pdf_cv_is_rejected(self):
		fake = SimpleUploadedFile('cv.pdf', b'<html><script>alert(1)</script>', content_type='application/pdf')
		response = self.patch_me(self.instructor, {'cv_resume': fake})
		self.assertEqual(response.status_code, 400)
		self.assertIn('cv_resume', response.json())

	def test_disallowed_extension_is_rejected(self):
		page = SimpleUploadedFile('cv.html', b'<html></html>', content_type='text/html')
		response = self.patch_me(self.instructor, {'cv_resume': page})
		self.assertEqual(response.status_code, 400)

	def test_fake_png_profile_photo_is_rejected(self):
		fake = SimpleUploadedFile('me.png', b'<svg onload=alert(1)>', content_type='image/png')
		response = self.patch_me(self.student, {'profile_photo': fake})
		self.assertEqual(response.status_code, 400)
		self.assertIn('profile_photo', response.json())

	def test_oversized_cv_is_rejected(self):
		big = pdf('cv.pdf', b'%PDF-1.4 ' + b'0' * (10 * 1024 * 1024))
		response = self.patch_me(self.instructor, {'cv_resume': big})
		self.assertEqual(response.status_code, 400)

	def test_docx_cv_is_accepted_and_downloaded_as_attachment(self):
		response = self.patch_me(self.instructor, {'cv_resume': docx()})
		self.assertEqual(response.status_code, 200, response.content)

		download = self.client.get(response.json()['cv_resume_url'])
		self.assertEqual(download.status_code, 200)
		self.assertIn('attachment', download['Content-Disposition'])
		self.assertEqual(download['Cache-Control'], 'private, no-store')

	def test_certificate_count_is_capped(self):
		files = [pdf(f'c{i}.pdf') for i in range(MAX_CERTIFICATE_FILES + 1)]
		response = self.patch_me(self.instructor, {'certificates_and_recommendations': files})
		self.assertEqual(response.status_code, 400)

	def test_registration_validates_instructor_documents(self):
		fake = SimpleUploadedFile('cv.pdf', b'MZ\x90\x00 not a pdf', content_type='application/pdf')
		response = self.client.post('/api/v1/register/instructor/', {
			'email': 'media-new@example.com', 'password': 'A-strong-password-123',
			'confirm_password': 'A-strong-password-123', 'name': 'New',
			'gender': 'male', 'dob': '1990-01-01', 'cv_resume': fake,
		}, format='multipart')
		self.assertEqual(response.status_code, 400)
		self.assertIn('cv_resume', response.json())

	def test_files_get_random_names_and_storage_names_not_urls(self):
		response = self.patch_me(self.student, {
			'profile_photo': png('My Holiday Photo.png'),
			'student_id_card': pdf('my-real-name-id.pdf'),
		})
		self.assertEqual(response.status_code, 200, response.content)

		self.student.refresh_from_db()
		self.assertRegex(self.student.profile_photo_url, r'^profile-photos/\d+/[0-9a-f]{32}\.png$')
		document = VerificationDocument.objects.get(user=self.student)
		self.assertRegex(document.file_url, r'^verification-documents/\d+/[0-9a-f]{32}\.pdf$')
		self.assertTrue(response.json()['profile_photo_url'].startswith('http://testserver/media/profile-photos/'))

	def test_legacy_url_values_still_resolve(self):
		self.assertEqual(media_src('/media/profile-photos/1/old.png'), '/media/profile-photos/1/old.png')
		self.assertEqual(media_src('profile-photos/1/new.png'), '/media/profile-photos/1/new.png')
		self.assertIsNone(media_src(''))
