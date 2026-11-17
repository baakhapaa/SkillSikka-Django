"""Book-only access, plain-text conversion and bounded EPUB import services."""
import hashlib
import json
import math
import posixpath
import re
import zipfile
import zlib
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.exceptions import APIException

from .book_files import _safe_entry, _validate_epub


class ReaderError(APIException):
    def __init__(self, code, detail, status=400):
        self.status_code = status
        super().__init__({'code': code, 'detail': detail})


def is_book_manager(user, book):
    role = getattr(getattr(user, 'role', None), 'name', '')
    return bool(user.is_authenticated and user.is_active and (
        user.is_superuser or role == 'super_admin'
        or (role == 'instructor' and book.uploaded_by_id == user.pk)))


def require_reader(user, book):
    if not is_book_manager(user, book):
        # Deliberately no price/payment-status based shortcut. Future entitlement
        # integration belongs here, with publication and revocation checks.
        raise ReaderError('BOOK_ACCESS_DENIED', 'A valid reader entitlement is required.', 403)


class _PlainText(HTMLParser):
    blocked = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template', 'head'}
    blocks = {'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'tr'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skipped = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.blocked:
            self.skipped.append(tag)
        if not self.skipped and tag in self.blocks:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if self.skipped:
            if tag == self.skipped[-1]:
                self.skipped.pop()
        elif tag in self.blocks:
            self.parts.append('\n')

    def handle_data(self, value):
        if not self.skipped:
            self.parts.append(value)


def plain_book_text(value):
    """Canonical text, not HTML: preserve examples, entities and whitespace.

    This operation is idempotent. Only newlines and unsafe C0 controls are
    normalized; decoded literal markup must never be parsed a second time.
    """
    text = (value or '').replace('\r\n', '\n').replace('\r', '\n')
    return ''.join(c for c in text if c in '\n\t' or ord(c) >= 32)


def html_to_book_text(value):
    """One-way boundary conversion for imported markup, never stored text."""
    parser = _PlainText()
    parser.feed(value or '')
    parser.close()
    text = ''.join(parser.parts)
    text = ''.join(c for c in text if c in '\n\t' or ord(c) >= 32)
    return plain_book_text('\n\n'.join(' '.join(line.split()) for line in text.splitlines() if line.strip()))


def chapter_digest(chapter):
    return hashlib.sha256(json.dumps([chapter.title, chapter.content, chapter.pdf_page_start,
        chapter.pdf_page_end], ensure_ascii=False).encode()).hexdigest()


def reading_minutes(content):
    return max(1, math.ceil(len(content.split()) / 200)) if content else 0


def validate_position(value):
    if not isinstance(value, dict) or set(value) - {'paragraph', 'offset', 'page'}:
        raise ValidationError('Position accepts only paragraph, offset and page integers.')
    for key, number in value.items():
        if type(number) is not int or number < (1 if key == 'page' else 0) or number > 10_000_000:
            raise ValidationError('Position values are outside their allowed range.')


def validate_chapter_position(chapter, value):
    validate_position(value)
    if 'page' in value and (not chapter.pdf_page_start
            or not chapter.pdf_page_start <= value['page'] <= chapter.pdf_page_end):
        raise ValidationError('Page must be within the chapter PDF range.')
    if 'paragraph' in value or 'offset' in value:
        paragraphs = chapter.content.split('\n\n') if chapter.content else ['']
        paragraph = value.get('paragraph', 0)
        if paragraph >= len(paragraphs) or value.get('offset', 0) > len(paragraphs[paragraph]):
            raise ValidationError('Paragraph or character offset is outside the chapter content.')


def _pdf_worker_result(book, start=None, end=None):
    """No shell, no caller-provided path, bounded source and isolated parsing."""
    import subprocess
    import sys
    if book.file_format != 'pdf' or not book.source_file:
        raise ReaderError('PDF_REQUIRED', 'A private PDF source is required.')
    try:
        path = book.source_file.path
        if not 0 < book.source_file.size <= 10 * 1024 * 1024:
            raise ReaderError('PDF_PROCESSING_LIMIT', 'Page-specific operations require a PDF no larger than 10 MiB. Use the protected viewer.')
        command = [sys.executable, '-m', 'core.book_pdf', path]
        command += ['inspect'] if start is None else ['extract', str(start), str(end)]
        result = subprocess.run(command, capture_output=True, timeout=15, check=True)
        if len(result.stdout) > 2 * 1024 * 1024:
            raise ValueError('Worker output limit.')
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError('Unexpected worker result.')
        count = data.get('page_count')
        if data.get('error') or type(count) is not int or not 1 <= count <= 10000:
            raise ValueError('Unverified PDF page count.')
        return data
    except ReaderError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise ReaderError('PDF_UNVERIFIABLE', 'PDF pages could not be verified. Use the protected viewer; no page-specific state was changed.') from exc


def pdf_page_count(book):
    """Cache only server-inspected counts, keyed by the current stored object.

    Upload replacements receive new UUID names. Stat metadata also invalidates
    the cache for local file changes. Nothing is fetched from a legacy URL.
    """
    from django.core.cache import cache
    from pathlib import Path
    if book.file_format != 'pdf' or not book.source_file:
        raise ReaderError('PDF_REQUIRED', 'A private PDF source is required.')
    try:
        info = Path(book.source_file.path).stat()
    except OSError as exc:
        raise ReaderError('PDF_UNVERIFIABLE', 'Private PDF source is unavailable.') from exc
    if not 0 < info.st_size <= 10 * 1024 * 1024:
        raise ReaderError('PDF_PROCESSING_LIMIT', 'Page-specific operations require a PDF no larger than 10 MiB. Use the protected viewer.')
    identity = json.dumps([book.source_file.name, book.source_file.path, info.st_size, info.st_mtime_ns, info.st_ctime_ns])
    key = 'book-pdf-pages-v1:' + hashlib.sha256(identity.encode()).hexdigest()
    count = cache.get(key)
    if type(count) is not int or not 1 <= count <= 10000:
        count = _pdf_worker_result(book)['page_count']
        cache.set(key, count, timeout=300)
    return count


def validate_pdf_range(book, start, end):
    if type(start) is not int or type(end) is not int or not 1 <= start <= end:
        raise ValidationError('Provide a valid inclusive PDF page range.')
    try:
        if end > pdf_page_count(book):
            raise ValidationError('PDF range exceeds the actual document page count.')
    except ReaderError as exc:
        raise ValidationError(str(exc.detail['detail'])) from exc


def validate_pdf_position(book, position):
    if 'page' not in position:
        return
    try:
        if position['page'] > pdf_page_count(book):
            raise ValidationError('Page exceeds the actual document page count.')
    except ReaderError as exc:
        raise ValidationError(str(exc.detail['detail'])) from exc


def _xml(body):
    if len(body) > 2 * 1024 * 1024:
        raise ValueError('XML member exceeds import size limit.')
    text = body.decode('utf-8-sig')
    if '\x00' in text or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('DTD/entities and non-UTF8 XML are unsupported.')
    if re.search(r'encoding\s*=\s*[\"\'](?!utf-8[\"\'])', text, re.I):
        raise ValueError('XML must use UTF-8.')
    return ElementTree.fromstring(text)


def _member(package, href):
    parsed = urlsplit(href)
    decoded = unquote(parsed.path)
    if parsed.scheme or parsed.netloc or parsed.query or not _safe_entry(decoded):
        raise ValueError('Unsafe EPUB reference.')
    name = posixpath.join(posixpath.dirname(package), decoded)
    if not _safe_entry(name):
        raise ValueError('Unsafe EPUB member.')
    return name


def parse_epub(book):
    if book.file_format != 'epub' or not book.source_file:
        raise ReaderError('EPUB_REQUIRED', 'Upload a private EPUB source first.')
    try:
        with book.source_file.open('rb') as stream:
            _validate_epub(stream)  # Revalidate stored bytes, never trust a prior upload.
            stream.seek(0)
            with zipfile.ZipFile(stream) as archive:
                container = _xml(archive.read('META-INF/container.xml'))
                rootfile = container.find('.//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile')
                package_name = rootfile.attrib['full-path']
                package = _xml(archive.read(package_name))
                ns = {'o': 'http://www.idpf.org/2007/opf'}
                items = package.findall('./o:manifest/o:item', ns)
                manifest = {item.attrib['id']: item for item in items}
                if len(manifest) != len(items):
                    raise ValueError('Duplicate manifest ID.')
                spine = package.findall('./o:spine/o:itemref', ns)
                if not spine or len(spine) > 500:
                    raise ValueError('EPUB requires 1-500 spine chapters.')
                results, seen, total = [], set(), 0
                for itemref in spine:
                    if itemref.get('linear', 'yes') == 'no':
                        continue
                    item = manifest[itemref.attrib['idref']]
                    if item.get('media-type') != 'application/xhtml+xml':
                        raise ValueError('Only XHTML spine content is supported.')
                    name = _member(package_name, item.attrib['href'])
                    if name in seen or len(name) > 500:
                        raise ValueError('Duplicate spine member.')
                    seen.add(name)
                    document = _xml(archive.read(name))
                    body = document.find('.//{http://www.w3.org/1999/xhtml}body')
                    if body is None:
                        raise ValueError('Chapter must contain an XHTML body.')
                    # ElementTree may use arbitrary namespace prefixes; normalize
                    # tags before feeding the HTML-to-text converter.
                    for node in body.iter():
                        node.tag = node.tag.rsplit('}', 1)[-1]
                    title = next((html_to_book_text(ElementTree.tostring(node, encoding='unicode')) for node in body.iter()
                        if node.tag in ('h1', 'h2', 'h3') and ''.join(node.itertext()).strip()), '')
                    content = html_to_book_text(ElementTree.tostring(body, encoding='unicode'))
                    if len(content) > 200_000:
                        raise ValueError('Chapter text exceeds 200000 characters.')
                    total += len(content)
                    if total > 2_000_000:
                        raise ValueError('Book text exceeds import limit.')
                    results.append({'source_reference': name, 'title': title[:200] or f'Chapter {len(results)+1}', 'content': content})
                if not results:
                    raise ValueError('No readable spine chapters.')
                return results
    except ReaderError:
        raise
    except (OSError, ValueError, KeyError, AttributeError, RuntimeError, zipfile.BadZipFile,
            ElementTree.ParseError, ValidationError, zlib.error, EOFError) as exc:
        raise ReaderError('INVALID_EPUB', 'EPUB could not be safely imported. No chapters were changed.') from exc


@transaction.atomic
def reorder_chapters(book, chapter_ids):
    from .models import EBook, BookChapter
    EBook.objects.select_for_update().get(pk=book.pk)
    chapters = list(BookChapter.objects.select_for_update().filter(book=book))
    if len(chapter_ids) != len(set(chapter_ids)) or set(chapter_ids) != {c.pk for c in chapters}:
        raise ReaderError('INVALID_ORDER', 'Supply every chapter ID exactly once.')
    by_id = {chapter.pk: chapter for chapter in chapters}
    ordered = [by_id[chapter_id] for chapter_id in chapter_ids]
    for index, chapter in enumerate(ordered, 1):
        chapter.chapter_number = 1_000_000 + index
    BookChapter.objects.bulk_update(ordered, ['chapter_number'], batch_size=100)
    for index, chapter in enumerate(ordered, 1):
        chapter.chapter_number = index
    BookChapter.objects.bulk_update(ordered, ['chapter_number'], batch_size=100)


def import_epub(book, mode='create'):
    from .models import EBook, BookChapter
    if mode not in ('create', 'refresh'):
        raise ReaderError('INVALID_MODE', 'Choose create or explicit refresh mode.')
    source = book.source_file.name
    parsed = parse_epub(book)
    with transaction.atomic():
        current = EBook.objects.select_for_update().get(pk=book.pk)
        if current.source_file.name != source:
            raise ReaderError('SOURCE_CHANGED', 'Source changed during import. Retry.', 409)
        existing = list(BookChapter.objects.select_for_update().filter(book=book))
        if existing and mode != 'refresh':
            raise ReaderError('REIMPORT_CONFIRMATION_REQUIRED', 'Use explicit refresh mode to reimport.', 409)
        references = {row['source_reference'] for row in parsed}
        if any(not c.source_reference or c.source_reference not in references or
               not c.imported_digest or chapter_digest(c) != c.imported_digest for c in existing):
            raise ReaderError('CHAPTER_CONFLICT', 'Manual edits or removed chapters require review; nothing was overwritten.', 409)
        by_reference = {c.source_reference: c for c in existing}
        for index, chapter in enumerate(existing, 1):
            BookChapter.objects.filter(pk=chapter.pk).update(chapter_number=1_000_000 + index)
        ids = []
        for index, row in enumerate(parsed, 1):
            chapter = by_reference.get(row['source_reference']) or BookChapter(book=book)
            chapter.chapter_number = index
            for field, value in row.items():
                setattr(chapter, field, value)
            chapter.save()
            # Hash exactly what the database now contains, after canonical save.
            chapter.refresh_from_db()
            BookChapter.objects.filter(pk=chapter.pk).update(imported_digest=chapter_digest(chapter))
            ids.append(chapter.pk)
        return {'created': len(parsed) - len(existing), 'updated': len(existing), 'chapter_ids': ids, 'content_format': 'text'}


def extract_pdf_chapter(book, chapter):
    if book.file_format != 'pdf' or not book.source_file or not chapter.pdf_page_start:
        raise ReaderError('PDF_RANGE_REQUIRED', 'A private PDF and explicit chapter page range are required.')
    try:
        source_size = book.source_file.size
    except OSError as exc:
        raise ReaderError('PDF_TEXT_UNAVAILABLE', 'Private PDF source is unavailable.') from exc
    if source_size > 10 * 1024 * 1024 or chapter.pdf_page_end-chapter.pdf_page_start >= 20:
        raise ReaderError('PDF_EXTRACTION_LIMIT', 'Text extraction is limited to 10 MiB PDFs and 20-page ranges. Use the protected PDF viewer.')
    if chapter.content:
        raise ReaderError('CHAPTER_CONFLICT', 'Existing authored text is never overwritten by PDF extraction.', 409)
    source = book.source_file.name
    try:
        data = _pdf_worker_result(book, chapter.pdf_page_start, chapter.pdf_page_end)
        if not data.get('content', '').strip():
            raise ValueError('No reliable text layer.')
        content = plain_book_text(data['content'])
        if not content or len(content) > 200_000:
            raise ValueError('Unsupported text.')
    except ValueError as exc:
        raise ReaderError('PDF_TEXT_UNAVAILABLE', 'No reliable text could be extracted. Use the protected PDF viewer or author text manually.') from exc
    from .models import EBook, BookChapter
    with transaction.atomic():
        locked = EBook.objects.select_for_update().get(pk=book.pk)
        current = BookChapter.objects.select_for_update().get(pk=chapter.pk, book=book)
        if locked.source_file.name != source or current.content or (current.pdf_page_start, current.pdf_page_end) != (chapter.pdf_page_start, chapter.pdf_page_end):
            raise ReaderError('CHAPTER_CONFLICT', 'Book source or chapter changed during extraction. Nothing was overwritten.', 409)
        current.content = content
        current.save()
        return current
