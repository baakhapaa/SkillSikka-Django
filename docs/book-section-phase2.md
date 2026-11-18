# Book Section Phase 2 — Flutter reader contract

## Scope and access

Built on Phase 1 `6bc3d38`, using the existing `core.EBook`. No Course, Bootcamp,
Payment or Enrollment integration is changed. No fake purchases or free grants.

Every endpoint requires `Authorization: Bearer <access-token>`. Existing email
verification and active-account checks apply. Reader access is currently limited
to administrators and **current instructor owners**, including draft previews.
All students, former instructor owners now in a student role, nonowner instructors,
and other roles are denied book content/progress/bookmarks/import actions. Null,
zero and positive prices never grant access. Book entitlements are not implemented;
do not enable student reading until a verified entitlement policy is integrated
into `require_reader` in `core/book_reader.py`. Settings alone are available to
all authenticated users because they disclose no book content.

Legacy book PUT/PATCH/DELETE now use that same current-role management policy.
An owner ID alone is insufficient after a role change to Student. Authorization
runs before update validation/upload storage; denied requests leave the book,
chapter rows, publication flags and source objects intact. Catalogue visibility
is unchanged. This intentionally closes the legacy mutation/cascade-deletion bypass.

Reader responses use `Cache-Control: private, no-store`. Catalogue routes and
Phase 1 uploads, ownership rules, legacy URL masking/explicit clearing remain.
No private path, storage URL, archive member name or import digest is returned.
The route `/api/v1/ebooks/{id}/content/` remains an authenticated attachment stream,
not a public URL or redirect. Never place its bytes in a public cache.

## Models and migration

`0054_book_reader_phase2` depends on `0053_ebook_phase1` and creates only:

| Model | Data / constraints |
| --- | --- |
| BookChapter | Existing book FK; unique chapter_number per book (1–10000); stable PK; title; plain-text content (200000 chars max); derived estimated_reading_minutes; optional inclusive PDF range; timestamps |
| BookReadingProgress | Unique user/book; nullable last chapter; structured position; last-read timestamp |
| BookChapterCompletion | Unique progress/chapter; completion timestamp |
| BookBookmark | User/book/chapter; position; optional anchor/note; unique normalized locator per user/chapter; timestamp |
| ReaderSettings | One per user; validated typography and theme |

Chapter `source_reference` and `imported_digest` are internal import identity/conflict
metadata. They are not writable via chapter APIs and are never reader response
fields. Unique book/source references prevent duplicate imports; manual chapters
have a null reference. No new fields are required on EBook. Existing books, URLs,
files, prices and publication flags are preserved. Migration tests upgrade real
Phase 1 fixtures and check preservation; no reset/fake migrations.

Schema rollback drops Phase 2 reader data. Export/back up chapters, settings,
progress and bookmarks before rollback. It does not delete the original sources.

## Endpoint summary

All API paths below start at `/api/v1/`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | ebooks/{book_id}/chapters/ | Contents, safe book metadata and this user's progress |
| POST | ebooks/{book_id}/chapters/ | Manager manual chapter creation |
| GET | ebooks/{book_id}/chapters/{chapter_id}/ | Chapter, navigation and user progress |
| PATCH | ebooks/{book_id}/chapters/{chapter_id}/ | Manager edit; no progress reset |
| DELETE | ebooks/{book_id}/chapters/{chapter_id}/ | Manager deletion |
| POST | ebooks/{book_id}/chapters/reorder/ | Atomic complete ordering |
| POST | ebooks/{book_id}/import-epub/ | Explicit safe import / refresh |
| POST | ebooks/{book_id}/chapters/{chapter_id}/extract-pdf/ | Explicit bounded text extraction for an empty manually ranged chapter |
| GET, PUT | ebooks/{book_id}/progress/ | Resume state and completion events |
| GET, POST | ebooks/{book_id}/bookmarks/ | This user's chapter bookmarks |
| DELETE | ebooks/{book_id}/bookmarks/{bookmark_id}/ | Owner-only removal |
| GET, PATCH | reader/settings/ | User-specific preferences |
| GET | reader/continue/ | Latest 20 accessible reading states, newest first |
| GET | ebooks/{id}/content/ | Existing private PDF/EPUB attachment |

New JSON write contracts reject unknown fields. All chapter/book/bookmark IDs are
scoped to the parent book and authenticated user as applicable. Existing catalogue
GET `/ebooks/` and GET `/ebooks/{id}/` contain no chapter contents. Contents itself
is access controlled and never includes chapter text.

## Contents screen

Example GET `/ebooks/12/chapters/` (book metadata abbreviated here):

```json
{
  "book": {"id": 12, "title": "Design", "file_url": "", "file_format": "epub"},
  "chapters": [
    {"id": 81, "chapter_number": 1, "title": "Introduction", "estimated_reading_minutes": 3,
     "pdf_page_start": null, "pdf_page_end": null, "is_completed": false}
  ],
  "progress": {"last_chapter_id": 81, "position": {"paragraph": 1, "offset": 4},
    "completed_chapter_ids": [], "total_chapters": 1, "completed_chapters": 0,
    "overall_percentage": 0, "last_read_at": "2026-11-17T10:00:00Z"},
  "reader_mode": "chapters"
}
```

Map `last_chapter_id` to the ordered list for the current marker and Continue
button. `reader_mode` is `chapters`, `protected_pdf` for chapterless PDFs, or
`import_required` for other chapterless books. Zero chapters do not imply zero
price or free access. The actual `book` object contains all safe Phase 1 fields.

## Chapter screen and authoring

GET `/ebooks/12/chapters/81/`:

```json
{
  "book": {"id": 12, "title": "Design", "file_url": ""},
  "chapter": {"id": 81, "chapter_number": 1, "title": "Introduction",
    "content": "Welcome.\n\nRead the first example.", "content_format": "text",
    "estimated_reading_minutes": 1, "pdf_page_start": null, "pdf_page_end": null,
    "created_at": "2026-11-17T10:00:00Z", "updated_at": "2026-11-17T10:00:00Z"},
  "previous_chapter_id": null, "next_chapter_id": 82,
  "progress": {"last_chapter_id": 81, "position": {}, "completed_chapter_ids": [],
    "total_chapters": 2, "completed_chapters": 0, "overall_percentage": 0, "last_read_at": null}
}
```

**Render `content` with Flutter Text/RichText as plain text, never as HTML or
executable WebView content.** Manual chapter inputs are literal text: angle
brackets, HTML-like code and entity spellings are preserved, not decoded/parsed.
Canonical storage normalizes CRLF/CR to LF and removes unsafe C0 controls while
retaining indentation, tabs, leading/trailing whitespace and line breaks.
Metadata-only edits and repeated saves do not reparse or alter canonical content.

EPUB XHTML crosses a separate one-way conversion boundary exactly once. Active
subtrees, attributes, asset requests and link targets are discarded there; escaped
code examples become readable text and are never interpreted again. Imported
paragraphs use two newlines; manually authored line breaks are preserved. Literal
tags can therefore appear in the JSON text, but they are not executable HTML.
Admin previews and textareas use Django escaping, never `safe`/`mark_safe`.

Use previous/next IDs supplied by the server; do not assume IDs are consecutive.
Manual POST body: `{"chapter_number":1,"title":"Intro","content":"Text"}`.
PATCH accepts those fields plus optional `pdf_page_start`/`pdf_page_end`. Titles
must remain nonblank. Reading time is derived at 200 words/minute.
Reordering uses `{"chapter_ids":[82,81]}` with every book chapter exactly once.
IDs, completion records and bookmarks remain stable across edits and reorder.

Deletion removes that chapter's bookmarks/completions and clears any resume
pointer/position referencing it. Other chapters' reader state remains. Original
source files are not deleted. The HTML admin requires a confirmation POST.

## Progress and Continue Reading

GET `/ebooks/12/progress/` returns the same `progress` shape as Contents. Before
the first update it has null last chapter/timestamp, empty position/completions,
and zero percentage. GET does not create or mutate a reading record.

PUT example:

```json
{"chapter_id":81,"position":{"paragraph":1,"offset":4},"completed":true}
```

`chapter_id` belongs to this book. Position accepts only nonnegative integer
`paragraph` and `offset`, and optional 1-based integer PDF `page`. Paragraphs are
zero-based; offsets count Unicode characters within the paragraph. Bounds are
validated against current chapter text and any declared PDF range. Booleans,
negative/oversized values and arbitrary JSON keys are rejected.

`completed:true` records a unique chapter completion; `completed:false` explicitly
reopens it. Omitting completed retains completion. Visiting/reopening a previously
completed chapter without that flag does not erase completion. PUT replaces the
saved location (omitted position becomes `{}`). Send debounced updates after
location changes and on exit; chapter GET alone does not advance progress.

Do not submit percentages, totals, user IDs or completed-ID arrays. They are
server controlled and rejected as input. Percentage is completed existing chapters
divided by existing chapter count. Editing text does not clear saved state; if
paragraphs change, Flutter should clamp an old locator to the displayed text.
Deleting or adding chapters can change the derived denominator.

Chapterless PDF position supports `{"chapter_id":null,"position":{"page":3}}`.
Without chapters there is no chapter-completion percentage or completion event.
Every supplied PDF page must also be within the actual server-inspected page
count, including chapterless PDF positions and bookmarks. Unverifiable page counts
reject page-specific writes with a controlled validation error. Positions remain
user-reported locations, not authoritative proof of reading/completion.

GET `/reader/continue/` returns `{"books":[{"book":{...},"progress":{...}}]}`,
ordered by last-read timestamp, maximum 20 entries. It never returns another
user's history or an instructor's nonowned books. It uses the same access policy;
currently students receive 403. Choose the saved chapter/position, or the protected
PDF viewer for a null-chapter PDF record. If a deleted chapter has cleared the
pointer, show Contents rather than inventing a resume location.

## Bookmarks

POST `/ebooks/12/bookmarks/`:

```json
{"chapter_id":81,"position":{"paragraph":1,"offset":0},"anchor":"intro-p1","note":"Revisit this example"}
```

Response 201 is `{"id":7,"chapter_id":81,"position":{"paragraph":1,"offset":0},
"anchor":"intro-p1","note":"Revisit this example","created_at":"..."}`.
Anchor and note are optional (120 safe identifier characters / 2000 text characters).
Repeating the same chapter/anchor returns the existing bookmark with 200 and does
not overwrite its note. Without an anchor, normalized position identifies the
bookmark; omitted paragraph/offset normalize to zero, and an omitted PDF page
normalizes to the declared range start. Same anchors in different chapters/users
remain independent. GET returns this user's array, newest first. DELETE returns
204; another user's bookmark ID or cross-book ID returns 404. No edit endpoint is
provided; delete/recreate explicitly to change notes/locations.

## Reading settings

GET `/reader/settings/` defaults:

```json
{"font_family":"system","font_size":18,"line_spacing":"1.5","theme":"light"}
```

PATCH any subset, for example `{"theme":"sepia","font_size":24}`. Font families:
system, serif, sans-serif, monospace. Font size: 12–32. Line spacing: 1.0–2.5 with
one decimal place. Themes: light/sepia/dark. Settings are isolated per user and
persist across devices. Brightness is Flutter/device controlled and rejected as
a backend field. PDF fixed-layout rendering may not support these typography
controls; apply them to plain-text/reflow readers.

## EPUB import and refresh

POST `/ebooks/12/import-epub/` with `{"mode":"create"}`. Response:
`{"created":2,"updated":0,"chapter_ids":[81,82],"content_format":"text"}`.

The private stored archive is revalidated using Phase 1 traversal, special-file,
encryption, duplicate-name, CRC and decompression protections. Nothing is extracted
to disk or served as an asset. UTF-8 container/package/XHTML are parsed with
DTD/entity declarations rejected. XML members are bounded at 2 MiB; at most 500
spine entries and 2 million extracted text characters are imported. Linear XHTML
spine order, not ZIP/manifest ordering, determines chapter order. Nonlinear spine
items are skipped. Heading text supplies titles; empty headings get numbered
fallbacks. Remote/unsafe hrefs and duplicate/missing spine references are rejected.
Images, embedded assets, JavaScript and CSS are not rendered or fetched.

Any malformed chapter aborts before database changes. Existing chapters require
explicit `{"mode":"refresh"}`. Refresh matches archive-relative identity and
retains chapter IDs. It refuses manually authored/edited chapters, missing old
members or a concurrent source replacement with 409. There is no force-overwrite
switch and no automatic deletion. Review/resolve conflicts manually; deletion
requires an explicit decision and removes dependent reader data.

Import digests are computed from the final persisted canonical text and title,
after saving. Unchanged refreshes, including escaped code examples, produce the
same digest; genuine manual edits still conflict. Refresh remains atomic, including
when a save fails part-way through. Existing data is not bulk-rewritten or silently
rehash-repaired; any old import conflict must be explicitly reviewed.

Replacing an uploaded source alone does not import, reset reader state or
silently replace chapters. Run import explicitly. Non-XHTML spine formats,
non-UTF8 XML and EPUB layouts relying on images/assets may require the original
protected EPUB in a trusted Flutter reader or manual chapter authoring. An empty
chapter can use that whole-file fallback; do not invent text.

## PDF behavior

PDF files remain in Phase 1 private storage and stream only through the protected
content route. No automatic chapter boundaries are inferred from page numbers.
Managers define inclusive 1-based ranges, for example
`{"chapter_number":1,"title":"Overview","pdf_page_start":1,"pdf_page_end":5}`.
Ranges require both ends and a PDF book; both structure and actual document page
count are checked for API and admin writes. Progress/bookmark page positions are
checked against the declared range and actual source page count. The server uses
bounded, isolated pypdf inspection; client page-count fields are never accepted.
Corrupt/encrypted/unverifiable PDFs reject page-specific operations without
changing state. Scanned PDFs with a valid page tree can still use page locations
and the protected viewer, even if no text layer exists.

Verified counts are cached for five minutes under a server-derived key containing
the stored UUID name and filesystem size/time metadata. Replacement uploads get
new UUIDs and cannot reuse a client's count. Source absence/limits are checked
before cache lookup. A failed inspection is not cached. No private path is exposed
in cache keys returned to clients, responses or validation errors.

POST the chapter's `/extract-pdf/` action with `{}` only when its content is empty.
It uses pinned pypdf 7.0.1 in a separate subprocess, with a 15-second timeout,
20-page-extraction/10-MiB-input/200000-character limits. Inspection additionally
limits documents to 10000 pages. Page-specific operations on larger sources are
rejected; the original protected viewer fallback remains available. POSIX adds CPU/address-space limits;
Windows has the timeout but no equivalent process memory cap. Existing authored
text is never overwritten. PDF actions are not executed. Parser errors, encrypted
PDFs, missing text, malformed/out-of-range content or limits yield safe errors,
not parser traces or storage paths. Managers should review extracted text.

Scanned/image PDFs require the protected Flutter PDF viewer or manually authored
text; OCR is not implemented. Large/complex PDFs also use the viewer fallback.
No external OCR/upload service receives the document. The attachment stream is
not a public URL; Flutter must send authorization and keep any local copy private.
Byte-range streaming/DRM and a dedicated PDF media server are not implemented.

Parser behavior reference: [pypdf PdfReader](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html)
and [text extraction limitations](https://pypdf.readthedocs.io/en/7.0.0/user/extract-text.html).

## Admin dashboard

Book edit links to `/admin/books/{id}/chapters`. It lists ordered chapters and
offers manual creation, complete ordering, explicit EPUB import/refresh, import
counts/IDs, and PDF extraction for author-defined ranges. Edit/escaped preview:
`/admin/books/{id}/chapters/{chapter_id}/edit`. Confirmed deletion:
`/admin/books/{id}/chapters/{chapter_id}/delete`. Every route requires the existing
administrator role; instructors use the authenticated management APIs instead.
All dashboard writes require CSRF. Errors leave source files and chapter state
intact. New chapter screens use the existing shared dashboard/sidebar.

PDF extraction chapter IDs are validated as positive signed-64-bit integers before
ORM lookup. Missing, malformed, zero/negative IDs produce a controlled form error;
unknown/cross-book IDs return 404. No traceback is rendered for these inputs.

## Errors and validation

| Status | Meaning |
| --- | --- |
| 400 | Invalid field/position/range/settings; malformed EPUB/PDF or unavailable extraction |
| 401 | Missing/invalid JWT or unverified email |
| 403 | No reader/management access (including paid, zero-price and unknown-price consumers) |
| 404 | Missing book/chapter, wrong parent ID, missing private source, or another user's bookmark |
| 409 | Reimport confirmation/conflict, concurrent source change, or existing PDF chapter text |
| 429 | Existing global request throttles |

Reader service errors use `{"code":"BOOK_ACCESS_DENIED","detail":"A valid reader entitlement is required."}`.
Other codes include INVALID_EPUB, REIMPORT_CONFIRMATION_REQUIRED, CHAPTER_CONFLICT,
SOURCE_CHANGED, INVALID_ORDER, PDF_RANGE_REQUIRED, PDF_EXTRACTION_LIMIT and
PDF_TEXT_UNAVAILABLE, plus PDF_REQUIRED, PDF_UNVERIFIABLE and PDF_PROCESSING_LIMIT.
Field validation uses normal DRF field error arrays. Do not
infer book ownership or payment success from status alone.

## Verification and limits

Focused coverage lives in `core.test_books`: Phase 1 compatibility/security plus
reader CRUD/navigation, spine order, XSS/DTD/malformed imports, safe refresh,
PDF text/scanned fallback, reader permissions/role transitions, isolated state,
server-derived completion, bookmark deduplication, validated settings, chapter
admin actions/CSRF, and legacy migration preservation. Throttle caches are isolated
per test; production limits remain unchanged. Relevant regressions are admin
logout, existing bootcamp dashboard, and media uploads.

Recorded validation after the five audit fixes: **99 book tests + 39 adjacent
regressions = 138 passed, zero failures**. The five exact audit reproductions
also passed in a separate focused run. `manage.py check`, `makemigrations --check --dry-run` and
`git diff --check` passed. Migration 0054 was applied to local SQLite after a
backup under ignored `private-books/backups/`; all existing EBook fields were
compared before/after (the local database contained zero books). Populated legacy
preservation is separately exercised by the migration tests. No reset/fake
migrations, commits or pushes were performed.

The audit fixes intentionally strengthen EBookDetailAPIView mutations in addition
to the shared EBookContentAPIView management guard. Existing catalogue visibility
and response keys remain. Existing EBook data and protected teammate definitions
are preserved; no audit-fix migration or bulk data conversion is introduced.
Course/Bootcamp/Payment/Enrollment and gateway files remain unchanged.

Modified files: `core/models.py`, `core/serializers.py`, `core/api_views.py`,
`core/api_urls.py`, `core/forms.py`, `core/views.py`, `core/urls.py`,
`core/test_books.py`, `requirements.txt`, `templates/admin/book_form.html`,
`templates/admin/book_navigation.html`.

Added files: `core/book_reader.py`, `core/book_pdf.py`,
`core/migrations/0054_book_reader_phase2.py`, `docs/book-section-phase2.md`,
`templates/admin/book_chapters.html`, `templates/admin/book_chapter_form.html`,
`templates/admin/book_chapter_delete.html`.

No student entitlement/purchase integration, OCR, embedded EPUB asset delivery,
rich HTML rendering, automatic PDF chapter inference or public content URLs.
Private source backups and legacy public-link revocation remain Phase 1 operating
requirements. Custom private roots must stay outside Docker build context or be
explicitly excluded. New dependencies must be installed from requirements.txt.
