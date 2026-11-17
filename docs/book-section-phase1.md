# Book Section — Phase 1

## Scope and architecture

Extends `core.EBook` / table `ebooks`. No second Book model, chapter schema,
purchase system, or payment changes. Models, serializers, API views and API routes
remain in their existing core modules. Upload/storage helpers live in
`core/book_files.py`. Dashboard forms/views reuse the existing session-authenticated
admin architecture. `core/admin.py` is unchanged: this project uses a custom
dashboard rather than mounting Django's standard admin site.

## Database fields

Preserved: `id`, `title` (200), `author` (200, optional), `description`, optional
`subject`/`grade` (SET_NULL), `uploaded_by` (PROTECT), `cover_url`, `file_url`,
`is_published`, `created_at`, `updated_at`. Ordering remains newest first.

Added:

| Field | Type/default |
| --- | --- |
| category | Optional CharField(100); book-specific label, independent of subject |
| difficulty | Optional beginner/intermediate/advanced; blank means unspecified |
| highlights | JSON list; default []; maximum 30 nonempty strings, 500 characters each |
| price | Decimal(10,2), nullable; minimum zero |
| currency | NPR only; default NPR |
| cover_image | Optional public ImageField; randomized `book-covers/<uuid>.<ext>` |
| source_file | Optional private FileField; randomized `content/<uuid>.pdf|epub` |
| file_format | Derived read-only pdf/epub; blank for unverified legacy URLs |
| published_at | Nullable, derived from publication changes |

Database constraints enforce nonnegative-or-null prices and NPR currency.
**Null price is unknown, never an implicit free book.** Zero is an explicit free
price, but does not grant reader access in Phase 1. New and legacy records can
remain unpriced without being silently assigned zero.

`is_published` remains the publication status; no duplicate status field.
Publishing records the timestamp; unpublishing clears it; republishing records a
new timestamp. Ordinary edits retain it. Drafts may be metadata-only. Publishing
requires a source upload or a legacy URL. Existing ownership and publication
authority are retained; no new editorial approval rule is introduced.

## Admin dashboard

| Route | Methods | Purpose |
| --- | --- | --- |
| /admin/books | GET | Paginated catalogue; q/title-author-description search, status and category filters |
| /admin/books/add | GET, POST | Create metadata/draft and upload assets |
| /admin/books/{id}/edit | GET, POST | Edit, replace files, publish/unpublish |
| /admin/books/{id}/delete | GET, POST | Confirmation page, then CSRF-protected confirmed deletion |

Shared navigation includes **Book Management** through the existing shared
navigation include. Anonymous requests redirect to login. Non-administrators get
403. Administrator means the existing superuser or `super_admin` rule; staff or
instructor membership alone does not qualify. Dashboard writes require CSRF.

Uploads use multipart forms. Leave file inputs empty to retain current files.
Unchecked `is_published` saves/unpublishes a draft. Uploading a replacement uses a
new random object name. Deleting a record does not delete uploaded objects;
unpublish instead to hide it while preserving the record. File cleanup is a
separate controlled operation, not a destructive side effect of a request.

## Existing API contracts

All routes remain JWT authenticated (including student/instructor email checks):

| Method | Route | Behavior |
| --- | --- | --- |
| GET, POST | /api/v1/ebooks/ | Existing catalogue/create |
| GET, PUT, PATCH, DELETE | /api/v1/ebooks/{id}/ | Existing retrieve/update/delete |
| GET | /api/v1/ebooks/{id}/content/ | Current instructor owner/admin source download only |

Catalogue visibility is unchanged: admin sees all; instructors see published plus
their own drafts; other authenticated users see published books. `subject` and
`grade` filters remain. Creation requires a verified instructor or admin.
Updates/deletion require owner/admin and existing visibility rules. Instructor
verification is still checked at creation, not added as a new ownership-write
requirement. Uploader attribution cannot be supplied or reassigned by clients.

Existing metadata keys remain. Added response keys are `category`, `difficulty`,
`highlights`, `price`, `currency`, `file_format`, `published_at`. Price is a decimal
string or null. Published records continue to expose `is_published`; drafts are
only visible under the existing rules.

`cover_url` prefers the uploaded image's URL, otherwise the legacy cover URL.
`source_file` and `cover_image` are write-only upload fields and are never returned.
`file_format`, `published_at`, uploader and timestamps are read-only.

**Intentional security compatibility change:** `file_url` remains a response key
but is always `""`, including manager responses. Legacy URL-based creation and
updates remain accepted. On ordinary PUT/PATCH updates an empty `file_url` is a
masked placeholder and leaves the stored reference unchanged, including GET-to-PUT
round trips for drafts and published books. A nonempty URL remains an intentional
replacement.

Explicit API clearing uses write-only `clear_file_url: true` on an existing book,
with no nonempty replacement `file_url` in that request. Only the administrator
or current instructor owner can clear it. A published book must retain a private
source upload, or be explicitly unpublished in the same operation. Otherwise the
request is rejected without clearing the original reference. The flag is never
returned and is not a model field. The administrator dashboard continues to show
the real legacy reference, so clearing that form field is explicit and remains
subject to the same published-book source validation. Existing direct-reader
clients must adapt; maintaining public content links would violate private delivery.

POST/PUT/PATCH accept JSON metadata, form data, or multipart. For multipart,
`source_file` is a PDF/EPUB, `cover_image` an image, and `highlights` a JSON array
string. No purchase/payment endpoints are introduced.

Example safe response (other original metadata keys omitted for brevity):

```json
{
  "id": 12,
  "title": "Practical Design",
  "author": "Example Author",
  "cover_url": "https://api.example.com/media/book-covers/random.png",
  "file_url": "",
  "category": "Design",
  "difficulty": "beginner",
  "highlights": ["Practical examples"],
  "price": "250.00",
  "currency": "NPR",
  "file_format": "epub",
  "is_published": true,
  "published_at": "2026-11-17T00:00:00Z"
}
```

The content route does not redirect to legacy URLs. Without a private upload it
returns 404; unauthorized users receive 403; anonymous users receive 401. It sends
an attachment with a generated filename, `private, no-store`, `nosniff` and a
sandbox CSP. It is management access, not the Phase 2 reader. Access requires an
administrator or a current instructor who owns the book. Ownership after changing
to the student role does not grant access, including paid or unknown-price drafts.
Neither zero price nor publication grants student source-file access.

## Upload validation and storage

- Source: PDF/EPUB only, nonempty, maximum 50 MiB.
- PDF: extension plus `%PDF-1.x`/`%PDF-2.0` signature and trailing EOF marker.
- EPUB: ZIP signature, uncompressed first `mimetype` entry containing exactly
  `application/epub+zip`, and a bounded UTF-8 `META-INF/container.xml` referencing
  an existing package.
- EPUB safety: at most 2000 entries, 20 MiB expanded per entry, 100 MiB expanded
  total, maximum 100:1 expansion ratio. Every member is streamed in bounded chunks
  for expansion and CRC checks. No extraction occurs.
- Reject traversal/absolute/backslash/control-character paths, duplicate names
  (case-insensitive), symlinks and special files, encryption, unsupported
  compression, DTD/entity container XML, malformed/corrupt archives.
- Cover: JPEG/PNG/WebP only, maximum 8 MiB; Pillow verifies format and image
  integrity, rejects decompression bombs and more than 40 million pixels.
- Client MIME types are not the authority for either source or cover validation.
- Original filenames are never storage paths; UUID names are used for both assets.

`BOOK_PRIVATE_ROOT` defaults to `<project>/private-books`, independently of the
default media backend. A Django system check and storage guard reject equal or
nested paths in either direction with `MEDIA_ROOT`, `STATIC_ROOT`, and every
`STATICFILES_DIRS` entry (including prefixed directory tuples). Canonical resolved
paths and path ancestry are used, not string prefixes. Empty/invalid paths and
existing regular files are rejected. Private storage refuses `.url()`; POSIX new-file/directory modes
are 0600/0700. Windows deployment requires appropriate filesystem ACLs.
`BOOK_MAX_UPLOAD_BYTES` and `BOOK_MAX_COVER_BYTES` configure application limits.

Public covers use the existing default storage, including S3 if configured.
Book sources deliberately use local private storage even when covers use S3.
`private-books/` is ignored by Git. Set `BOOK_PRIVATE_ROOT` through environment
configuration if needed; never mount it under a public media/static alias.
Docker Compose mounts `book_private_volume` only into Django at
`/app/private-books`, not into nginx. Custom roots require matching private volume
configuration. Back up this directory along with the database; multiple Django
instances require a shared private filesystem or a future private object backend.

`.dockerignore` excludes environment/credential files, private books and backups,
SQLite databases and sidecars, runtime media/uploads, VCS metadata, local virtual
environments and caches/temporary files. Application code, migrations, templates,
static source assets, requirements and `manage.py` stay in the build context.
Git ignore rules alone do not provide Docker context protection. Regression
fixtures verify positive exclusion rules and required application inclusions
without opening any secrets. A Docker image build was not run: the Docker CLI is
not installed in this environment. Confirm the resulting image in deployment QA.

The existing nginx 70 MB request cap accommodates one 50 MiB book plus an 8 MiB
cover. Any additional deployment proxy limits must be configured consistently.

## Migration and legacy records

`0053_ebook_phase1` depends on `0052_seed_premium_categories`. It only changes the
existing EBook table: nine added fields, optional legacy `file_url`, two check
constraints, and publication timestamp backfill. No other model is altered.

Legacy records retain IDs, metadata, owner, subject/grade, URLs, publication flags,
and original created/updated timestamps. New metadata defaults are blank/[];
price is null, currency NPR, and private upload is empty. Previously published
records receive `published_at=created_at` as an approximation; draft timestamps
remain null. The migration does not fetch remote files, change publication,
grant access, or invent prices.

Before local application, the migration plan was checked to contain only 0053,
SQLite was backed up under ignored `private-books/backups/`, and all original book
fields were compared before/after. This local database contained zero books.
Preservation of actual legacy published/draft records is covered by a real
MigrationExecutor test from 0052 to 0053. No database reset or fake migration.

Rolling the schema back removes new fields, so back up/export new metadata first.
Rollback does not delete private objects or revoke previously shared URLs.

## Phase 2 reader design — proposed, not implemented

Choose whether books use structured chapters, whole-file readers, or both before
introducing schema. Proposed `BookChapter` remains in `core/models.py` and links
to the existing `EBook`:

- `book` FK (`related_name='chapters'`), title and deterministic order.
- Content text/sanitized HTML or a private asset reference; choose one documented
  format and validate it. Optional grouping labels only if required by the UI.
- `is_preview`, timestamps and content version/import locator.
- Book-scoped ordering constraints and cross-book relationship validation.

Do not reuse academic `Chapter` solely because subject/grade match; it describes
shared academic taxonomy and has no book ownership relationship. Do not create
another root Book model or fake courses/enrollments.

Proposed reader contracts:

| Route | Contract |
| --- | --- |
| GET /ebooks/{id}/contents/ | Ordered chapter metadata; content not embedded; locked/preview state |
| GET /ebooks/{id}/chapters/{chapter_id}/ | Authorized content, previous/next IDs, version and stable locator metadata |
| GET/PATCH /ebooks/{id}/progress/ | Current chapter/locator, bounded progress and last-read version |
| GET/POST /ebooks/{id}/bookmarks/ | User-private stable locations and optional labels |
| DELETE /ebooks/{id}/bookmarks/{bookmark_id}/ | Owner-only removal |
| GET /my-books/ | Explicit entitlements/library and resumable state |

Use EPUB CFI/text anchors or format-aware PDF locations rather than typography-
dependent page numbers. Validate chapter membership and locator bounds. Define
version changes and stale-location behavior before saving reading state.

Purchase access requires an explicit book entitlement integrated with the existing
payment owner's settlement contract, including amount/currency verification,
idempotency, refunds/revocation and failure handling. Current Payment requires
Course and Enrollment and cannot purchase books unchanged. Phase 1 changes none
of those models, payment serializers, gateway code, callbacks or settlement logic.

Reader fonts, size, spacing, theme and brightness can remain local to Flutter.
Only add backend preferences when cross-device synchronization is required.
EPUB imports must revalidate archives and sanitize rendered content; do not
execute scripts or trust embedded external resources.

## Tests and limitations

`core.test_books` covers API compatibility, metadata/pricing, signature-checked
uploads, size limits, hostile paths/ZIP entries, private storage, authentication,
ownership/drafts/publication, URL leakage, download headers, dashboard permissions,
CSRF, uploads/replacements/deletion, and actual legacy migration preservation.

Required checks:

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test core.test_books --noinput
git diff --check
```

Adjacent regressions: `core.test_admin_logout`, `core.test_bootcamp_dashboard`,
`core.test_media_uploads`. There were no pre-existing dedicated eBook tests.

The initial implementation passed 41 book tests and 39 adjacent regression tests.
The final audit exposed role-transition access, masked-URL round-trip loss, public
static storage overlap, and missing Docker exclusions. These now have persistent
regression coverage in `core.test_books`, including the explicit URL-clear contract.
No additional migration is required for these fixes.
Final fix verification: all 55 book tests and all 39 adjacent regressions passed
(94 total, zero failures). Django system checks, migration drift checks and
`git diff --check` passed. Docker engine verification remains unavailable locally.
AST comparison confirmed existing Course/Bootcamp/Payment/Enrollment definitions
and payment/enrollment serializers are unchanged. Payment gateway files have no diff.

Changed-file inventory:

- Modified: `.env.example`, `.gitignore`, `config/settings.py`,
  `core/models.py`, `core/serializers.py`, `core/api_views.py`, `core/api_urls.py`,
  `core/forms.py`, `core/views.py`, `core/urls.py`, `docker-compose.yml`,
  `templates/admin/course_navigation.html`.
- Added: `.dockerignore`, `core/book_files.py`, `core/migrations/0053_ebook_phase1.py`,
  `core/test_books.py`, `docs/book-section-phase1.md`,
  `templates/admin/book_navigation.html`, `templates/admin/books.html`,
  `templates/admin/book_form.html`, `templates/admin/book_delete.html`.

Branch: `feature/ict-ai-bootcamp-admin`. Changes are uncommitted; no push performed.

Known limits: no chapters/import/extraction, progress, bookmarks, reviews,
wishlist, cart, reader entitlement, or purchase endpoints. No automatic malware
scan, complete PDF/EPUB standards validation, PDF sanitization, DRM, range-request
reader delivery, or remote legacy download/import. Upload validation cannot prove
an arbitrary PDF is harmless to every third-party reader; the server never renders
or executes it. Invalid/unsupported uploads are rejected, not repaired.

Legacy external/public URLs remain stored for compatibility and admin review.
Suppressing them in responses cannot revoke links already shared or secure an
external host. Administrators must upload private copies and revoke old public
objects through the owning storage service before selling legacy content.
Retained replaced/deleted files need an explicit retention/cleanup policy.
