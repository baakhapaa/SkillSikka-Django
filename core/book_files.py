"""Book upload validation and private storage; never extract or render EPUBs."""
from pathlib import Path
import re
import stat
from uuid import uuid4
import warnings
import zipfile
import zlib
from xml.etree import ElementTree

from django.conf import settings
from django.core.checks import Error, register
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from PIL import Image, UnidentifiedImageError


def private_root():
    def resolve_directory(value):
        # Some Windows path APIs return a nonexistent path rather than raising
        # for embedded NULs. Reject control characters before canonicalization.
        if not value or any(ord(character) < 32 for character in str(value)):
            raise ImproperlyConfigured('Invalid book storage directory configuration.')
        return Path(value).resolve()

    try:
        if not settings.BOOK_PRIVATE_ROOT:
            raise ImproperlyConfigured('BOOK_PRIVATE_ROOT must be a non-empty directory path.')
        root = resolve_directory(settings.BOOK_PRIVATE_ROOT)
        public_roots = [('MEDIA_ROOT', settings.MEDIA_ROOT or settings.BASE_DIR / 'media')]
        if settings.STATIC_ROOT:
            public_roots.append(('STATIC_ROOT', settings.STATIC_ROOT))
        for entry in settings.STATICFILES_DIRS:
            # Django accepts both a directory and a (URL prefix, directory) pair.
            directory = entry[1] if isinstance(entry, (tuple, list)) else entry
            public_roots.append(('STATICFILES_DIRS', directory))
        for label, directory in public_roots:
            public = resolve_directory(directory)
            # Path ancestry handles siblings, canonical paths and drive boundaries.
            if root == public or root in public.parents or public in root.parents:
                raise ImproperlyConfigured(f'BOOK_PRIVATE_ROOT must not overlap {label}.')
        if root.exists() and not root.is_dir():
            raise ImproperlyConfigured('BOOK_PRIVATE_ROOT must be a directory.')
    except (OSError, RuntimeError, ValueError, TypeError, IndexError) as exc:
        raise ImproperlyConfigured('Invalid book storage directory configuration.') from exc
    return root


@register()
def check_book_storage(app_configs, **kwargs):
    try:
        private_root()
    except ImproperlyConfigured as exc:
        return [Error(str(exc), id='core.EBookStorage')]
    return []


@deconstructible
class PrivateBookStorage(FileSystemStorage):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('file_permissions_mode', 0o600)
        kwargs.setdefault('directory_permissions_mode', 0o700)
        super().__init__(*args, **kwargs)

    @property
    def location(self):
        return str(private_root())

    @property
    def base_location(self):
        return str(private_root())

    def url(self, name):
        raise ValueError('Private book files have no public URL.')


def book_source_path(instance, filename):
    return f'content/{uuid4().hex}{Path(filename).suffix.lower()}'


def book_cover_path(instance, filename):
    return f'book-covers/{uuid4().hex}{Path(filename).suffix.lower()}'


def validate_highlights(value):
    if (not isinstance(value, list) or len(value) > 30
            or any(not isinstance(item, str) or not item.strip() or len(item) > 500 for item in value)):
        raise ValidationError('Use at most 30 non-empty highlight strings, each at most 500 characters.')


def _safe_entry(name):
    parts = name.rstrip('/').split('/')
    return (bool(name) and not name.startswith('/') and '\\' not in name
            and ':' not in name and not any(ord(c) < 32 for c in name)
            and all(part not in ('', '.', '..') for part in parts))


def _validate_epub(upload):
    total = 0
    with zipfile.ZipFile(upload) as archive:
        entries = archive.infolist()
        if not entries or len(entries) > 2000:
            raise ValidationError('EPUB must contain between 1 and 2000 entries.')
        names = set()
        for entry in entries:
            folded = entry.filename.casefold()
            mode = entry.external_attr >> 16
            if (not _safe_entry(entry.orig_filename) or not _safe_entry(entry.filename)
                    or folded in names or entry.flag_bits & 1
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise ValidationError('EPUB contains an unsafe, duplicate, encrypted or unsupported entry.')
            names.add(folded)
            total += entry.file_size
            if (entry.file_size > 20 * 1024 * 1024 or total > 100 * 1024 * 1024
                    or entry.file_size > max(entry.compress_size, 1) * 100):
                raise ValidationError('EPUB decompression limits exceeded.')
        first = entries[0]
        if (first.filename != 'mimetype' or first.compress_type != zipfile.ZIP_STORED
                or first.file_size != 20 or archive.read(first) != b'application/epub+zip'):
            raise ValidationError('EPUB requires its uncompressed mimetype entry first.')
        # Read every member in bounded chunks to check CRC and actual expanded size.
        actual_total = 0
        for entry in entries:
            actual_entry = 0
            with archive.open(entry) as member:
                while chunk := member.read(64 * 1024):
                    actual_entry += len(chunk)
                    actual_total += len(chunk)
                    if actual_entry > 20 * 1024 * 1024 or actual_total > 100 * 1024 * 1024:
                        raise ValidationError('EPUB decompression limits exceeded.')
        container = archive.read('META-INF/container.xml')
        if len(container) > 256 * 1024 or b'<!DOCTYPE' in container.upper() or b'<!ENTITY' in container.upper():
            raise ValidationError('Unsafe EPUB container XML.')
        # Restrict container XML to UTF-8; alternate encodings could hide declarations.
        xml = container.decode('utf-8-sig')
        if '\x00' in xml or re.search(r'encoding\s*=\s*[\"\'](?!utf-8[\"\'])', xml, re.I):
            raise ValidationError('EPUB container must use UTF-8.')
        root = ElementTree.fromstring(xml)
        files = root.findall('.//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile')
        if not files or any(not _safe_entry(f.get('full-path', ''))
                            or f.get('full-path') not in archive.namelist() for f in files):
            raise ValidationError('EPUB container must reference an existing package.')


def validate_book_source(upload):
    if getattr(upload, '_committed', False):
        return  # Unchanged stored files were validated at upload time.
    extension = Path(upload.name).suffix.lower()
    if extension not in ('.pdf', '.epub'):
        raise ValidationError('Upload a PDF or EPUB file.')
    if not upload.size or upload.size > settings.BOOK_MAX_UPLOAD_BYTES:
        raise ValidationError(f'Book file must be non-empty and at most {settings.BOOK_MAX_UPLOAD_BYTES} bytes.')
    try:
        upload.seek(0)
        head = upload.read(16)
        if extension == '.pdf':
            if not re.match(rb'%PDF-(?:1\.[0-9]|2\.0)(?:\s|$)', head):
                raise ValidationError('File content does not match PDF format.')
            upload.seek(max(0, upload.size - 2048))
            if b'%%EOF' not in upload.read(2048):
                raise ValidationError('PDF is missing its end marker.')
        else:
            if not head.startswith(b'PK\x03\x04'):
                raise ValidationError('File content does not match EPUB format.')
            upload.seek(0)
            _validate_epub(upload)
    except (zipfile.BadZipFile, KeyError, RuntimeError, OSError, ValueError, zlib.error, EOFError,
            ElementTree.ParseError, UnicodeError, NotImplementedError) as exc:
        raise ValidationError('Invalid or unsafe book file.') from exc
    finally:
        upload.seek(0)


def validate_book_cover(upload):
    if getattr(upload, '_committed', False):
        return
    formats = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP'}
    extension = Path(upload.name).suffix.lower()
    if extension not in formats or not upload.size or upload.size > settings.BOOK_MAX_COVER_BYTES:
        raise ValidationError('Upload a JPEG, PNG or WebP cover within the configured size limit.')
    try:
        upload.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(upload) as picture:
                if picture.format != formats[extension] or picture.width * picture.height > 40_000_000:
                    raise ValidationError('Invalid cover image dimensions or format.')
                picture.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValidationError('Invalid cover image.') from exc
    finally:
        upload.seek(0)
