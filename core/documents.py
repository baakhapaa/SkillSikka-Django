"""Validation, storage and serving of user-uploaded media."""
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse
from uuid import uuid4
import warnings
import zipfile

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from PIL import Image, UnidentifiedImageError
from rest_framework import serializers


MAX_CERTIFICATE_FILES = 5

_SIGNATURES = {
	'.jpg': (b'\xff\xd8\xff',),
	'.jpeg': (b'\xff\xd8\xff',),
	'.png': (b'\x89PNG\r\n\x1a\n',),
	'.pdf': (b'%PDF-',),
	'.doc': (b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1',),
	'.docx': (b'PK\x03\x04',),
}
_IMAGE_FORMATS = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG'}
_CONTENT_TYPES = {
	'.jpg': {'image/jpeg'},
	'.jpeg': {'image/jpeg'},
	'.png': {'image/png'},
	'.pdf': {'application/pdf'},
	'.doc': {'application/msword'},
	'.docx': {
		'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
	},
}
# Generic types some clients send for any file; the content check still runs.
_GENERIC_CONTENT_TYPES = {'application/octet-stream', 'binary/octet-stream'}


def _content_matches(uploaded_file, extension):
	uploaded_file.seek(0)
	head = uploaded_file.read(16)
	uploaded_file.seek(0)

	if not any(head.startswith(sig) for sig in _SIGNATURES[extension]):
		return False

	if extension in _IMAGE_FORMATS:
		return _is_safe_image(uploaded_file, _IMAGE_FORMATS[extension])

	if extension == '.docx':
		try:
			with zipfile.ZipFile(uploaded_file) as archive:
				return 'word/document.xml' in archive.namelist()
		except zipfile.BadZipFile:
			return False
		finally:
			uploaded_file.seek(0)

	return True


def _is_safe_image(uploaded_file, expected_format):
	try:
		with warnings.catch_warnings():
			warnings.simplefilter('error', Image.DecompressionBombWarning)
			with Image.open(uploaded_file) as image:
				width, height = image.size
				if (
					image.format != expected_format
					or width > 8192 or height > 8192
					or width * height > 40_000_000
				):
					return False
				image.verify()
		return True
	except (
		UnidentifiedImageError, OSError, ValueError, SyntaxError,
		Image.DecompressionBombError, Image.DecompressionBombWarning,
	):
		return False
	finally:
		uploaded_file.seek(0)


def _validate_upload(uploaded_file, label, extensions, max_size_mb):
	extension = Path(uploaded_file.name).suffix.lower()
	allowed = ', '.join(ext.lstrip('.').upper() for ext in extensions)
	type_error = f'{label} must be a {allowed} file.'

	if extension not in extensions:
		raise serializers.ValidationError(type_error)

	content_type = (getattr(uploaded_file, 'content_type', None) or '').lower()
	if (
		content_type
		and content_type not in _CONTENT_TYPES[extension]
		and content_type not in _GENERIC_CONTENT_TYPES
	):
		raise serializers.ValidationError(type_error)

	if uploaded_file.size > max_size_mb * 1024 * 1024:
		raise serializers.ValidationError(
			f'{label} must not exceed {max_size_mb} MB.'
		)

	if not _content_matches(uploaded_file, extension):
		raise serializers.ValidationError(
			f'{label} content does not match its file type, or the file is damaged.'
		)

	return uploaded_file


def validate_profile_photo_file(uploaded_file):
	return _validate_upload(
		uploaded_file, 'Profile photo', ('.jpg', '.jpeg', '.png'), 5
	)


def validate_student_id_card_file(uploaded_file):
	return _validate_upload(
		uploaded_file, 'Student ID card', ('.jpg', '.jpeg', '.png', '.pdf'), 10
	)


def validate_cv_resume_file(uploaded_file):
	return _validate_upload(
		uploaded_file, 'CV / resume', ('.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png'), 10
	)


def validate_certificate_file(uploaded_file):
	return _validate_upload(
		uploaded_file, 'Certificate', ('.pdf', '.jpg', '.jpeg', '.png'), 10
	)


def validate_certificate_files(uploaded_files):
	if len(uploaded_files) > MAX_CERTIFICATE_FILES:
		raise serializers.ValidationError(
			f'Upload at most {MAX_CERTIFICATE_FILES} certificates at a time.'
		)

	for uploaded_file in uploaded_files:
		validate_certificate_file(uploaded_file)

	return uploaded_files


def save_upload(uploaded_file, folder, user_id):
	"""Store the file under a random name and return its storage name."""
	extension = Path(uploaded_file.name).suffix.lower()
	return default_storage.save(
		f'{folder}/{user_id}/{uuid4().hex}{extension}',
		uploaded_file,
	)


def storage_name(stored):
	"""Storage name for a stored value: a name, or a legacy URL to one."""
	path = unquote(urlparse(stored).path).lstrip('/')
	media_prefix = (getattr(settings, 'MEDIA_URL', '') or '').strip('/')

	if media_prefix and path.startswith(media_prefix + '/'):
		path = path[len(media_prefix) + 1:]

	return path


def media_src(stored):
	"""Current URL for a stored media value, or None when unset."""
	if not stored:
		return None

	return default_storage.url(storage_name(stored))


def document_file_response(document):
	name = storage_name(document.file_url)

	if not name or not default_storage.exists(name):
		raise Http404('Document file is missing.')

	extension = PurePosixPath(name).suffix.lower()
	response = FileResponse(
		default_storage.open(name, 'rb'),
		# Word files are downloaded; images and PDFs open in the browser.
		as_attachment=extension in {'.doc', '.docx'},
		filename=f'{document.document_type}{extension}',
	)
	response['Cache-Control'] = 'private, no-store'
	return response
