from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404


def storage_name(file_url):
	# file_url holds default_storage.url(name); recover name from its path.
	path = unquote(urlparse(file_url).path).lstrip('/')
	media_prefix = (getattr(settings, 'MEDIA_URL', '') or '').strip('/')

	if media_prefix and path.startswith(media_prefix + '/'):
		path = path[len(media_prefix) + 1:]

	return path


def document_file_response(document):
	name = storage_name(document.file_url)

	if not name or not default_storage.exists(name):
		raise Http404('Document file is missing.')

	return FileResponse(
		default_storage.open(name, 'rb'),
		filename=PurePosixPath(name).name,
	)
