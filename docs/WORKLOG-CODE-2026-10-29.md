# Code Worklog — 2026-10-29

Symbol-level inventory of the code written in `D:\SkillSikka-Django` on
29 October 2026.

Companion document: `docs/WORKLOG-2026-10-29.md` covers the *why* and the
narrative. This one covers the *what* — files, classes, functions, endpoints,
migrations, and the invariants the code now depends on.

Source: `git diff 45312d3~1 4a41519` (10 commits, 12:18 → 14:46).

---

## Change inventory

22 files, **+1,585 / −114**.

| File | + | − |
| --- | ---: | ---: |
| `core/test_course_discussions.py` *(new)* | 315 | 0 |
| `core/test_course_resources.py` *(new)* | 206 | 0 |
| `core/api_views.py` | 157 | 1 |
| `core/test_payments.py` | 155 | 2 |
| `core/bootcamp_views.py` | 109 | 46 |
| `core/test_mark_paid.py` *(new)* | 94 | 0 |
| `core/management/commands/mark_paid.py` *(new)* | 75 | 0 |
| `core/migrations/0048_…discussion…py` *(new)* | 69 | 0 |
| `core/payments.py` | 60 | 12 |
| `core/serializers.py` | 57 | 3 |
| `core/migrations/0049_…resource…py` *(new)* | 55 | 0 |
| `core/models.py` | 53 | 13 |
| `core/test_bootcamps.py` | 50 | 17 |
| `core/payment_views.py` | 32 | 1 |
| `core/migrations/0047_course_language_course_level.py` *(new)* | 27 | 0 |
| `core/test_course_batch2.py` | 23 | 0 |
| `core/api_urls.py` | 22 | 6 |
| `config/settings.py` | 13 | 0 |
| `core/management/commands/seed_bootcamps.py` | 8 | 8 |
| `core/bootcamp_serializers.py` | 3 | 3 |
| `core/views.py` | 1 | 1 |
| `core/management/commands/recheck_payments.py` | 1 | 1 |

---

## New endpoints

| Method | Path | View | Access |
| --- | --- | --- | --- |
| `POST` | `/api/v1/courses/{id}/assets/` | `CourseAssetUploadAPIView` | owner or admin |
| `GET` | `/api/v1/courses/{id}/enrollment/` | `CourseEnrollmentAPIView` | authenticated; own row only |
| `GET` `POST` | `/api/v1/courses/{id}/resources/` | `CourseResourceListAPIView` | read: enrolled or staff · write: course manager |
| `PUT` `PATCH` `DELETE` | `/api/v1/courses/{id}/resources/{rid}/` | `CourseResourceDetailAPIView` | course manager |
| `GET` `POST` | `/api/v1/courses/{id}/discussions/` | `CourseDiscussionListAPIView` | read: any authenticated · write: owner/roster/enrolled |
| `PATCH` `DELETE` | `/api/v1/courses/{id}/discussions/{did}/` | `CourseDiscussionDetailAPIView` | author, owner, or admin |
| `POST` `DELETE` | `/api/v1/courses/{id}/discussions/{did}/like/` | `CourseDiscussionLikeAPIView` | read access to the course |

`CourseResourceDetailAPIView` subclasses both `UpdateAPIView` and
`DestroyAPIView`; `CourseDiscussionDetailAPIView` and
`CourseDiscussionLikeAPIView` are `GenericAPIView` with explicit handlers, so
only the verbs listed above resolve.

---

## Models

### `Course` — two fields added

```python
level    = CharField(max_length=20, choices=LEVEL_CHOICES, blank=True, default='')
language = CharField(max_length=50, blank=True, default='English')
```

Both optional with defaults, so existing rows and clients that omit them are
unaffected. `LEVEL_CHOICES` = beginner / intermediate / advanced.

### `BootcampResource` → `CourseResource`

```python
class CourseResource(models.Model):
    course = ForeignKey(Course, on_delete=CASCADE, related_name='course_resources')
    lesson = ForeignKey('Lesson', on_delete=CASCADE, null=True, blank=True,
                        related_name='resources')
```

Renamed because it was never bootcamp-specific. `lesson` is new and nullable: a
file may belong to the specific lesson that teaches it, or to the course as a
whole. Deleting a lesson now cascades to its resources — pinned by
`test_lesson_delete_takes_its_resources`.

### `BootcampDiscussion` → `CourseDiscussion`

```python
class CourseDiscussion(models.Model):
    course = ForeignKey(Course, on_delete=CASCADE, related_name='course_discussions')
    author = ForeignKey(User, on_delete=CASCADE, related_name='course_discussions')
```

Same shape as before; only the name and related names changed.
`DiscussionLike` follows: `course_discussion_likes`.

---

## Migrations

| Migration | Kind | Note |
| --- | --- | --- |
| `0047_course_language_course_level` | added (renamed from 0046) | renumber to keep a single leaf after bootcamp `0046` landed on main |
| `0048_rename_bootcamp_discussion_course_discussion` | **hand-written** | `makemigrations` proposes Create + Delete and would drop every thread |
| `0049_rename_bootcamp_resource_course_resource` | **hand-written** | same hazard, would drop every file row |

All three are applied. `makemigrations --check --dry-run` reports no drift.

---

## Access control

Three helpers now sit in `core/bootcamp_views.py`, layered deliberately:

```python
course_for(request, course_id, *, access=False)
    # any course; published or staff. access=True adds owner/roster/enrolment.

require_course_manager(user, course)
    # admin, owner, or roster instructor. Deliberately NOT course_for(access=True),
    # which also passes an enrolled student — right for reading and commenting,
    # wrong for attaching or deleting a file.

bootcamp_for(request, course_id, *, write=False, access=False)
    # retained; still filters course_type='bootcamp'
```

`require_course_manager` exists because a bootcamp's `coach` teaches without
owning, so `is_course_manager()` alone would mute every teaching assistant.

---

## Payments — `core/payments.py`

The apply step was extracted so the gateway path and the manual path cannot
diverge:

```python
settle_payment(payment_id, new_status, gateway_transaction_id='', body=None)
    # The single place a payment changes state. Applies exactly once.

refresh_payment(payment_id, *, settle_missing=False)
    # read → ask gateway (outside any transaction) → lock → re-check → settle
```

Invariants the code now relies on:

1. **The gateway is never called inside `transaction.atomic()`.** Holding a row
   lock across a 15-second HTTP round trip caused 15/18 concurrent requests to
   fail with `database is locked`.
2. **The re-check happens under the lock.** It is the only guard that works on
   SQLite, where `select_for_update()` is silently a no-op — the backend has no
   `SELECT … FOR UPDATE`.
3. **`NOT_FOUND` does not settle.** It leaves the row `initiated` unless
   `settle_missing=True`. Only the `recheck_payments` sweeper (5-minute age) and
   an admin recheck pass it. Client-triggered reads are reads.
4. **Only a `successful` row unlocks a course.**

`core/payment_views.py` gains:

```python
class _AppRedirect(HttpResponseRedirect):
    allowed_schemes = {..., 'skillsikka'}
```

Django's `redirect()` trusts only http/https/ftp and raised
`DisallowedRedirect` for the `skillsikka://` deep link, which surfaced as a 400
*after* payment. `_refresh_quietly` additionally swallows `OperationalError` so
a busy row cannot render an error page to a student whose money has moved.

`config/settings.py` — SQLite only: 20-second busy timeout, `IMMEDIATE`
transactions (the default 5 s is shorter than the overlap the app creates by
design, and `DEFERRED`'s late lock upgrade is the case SQLite cannot resolve by
waiting).

---

## Management commands

### `mark_paid` *(new)*

```
manage.py mark_paid <id> [--status] [--reference]
```

Settles a payment without the gateway, for when eSewa's test environment is
unusable (exhausted reCAPTCHA quota). **Refuses to run when
`PAYMENT_MODE=live`.** Calls `settle_payment`, so enrolment activation and the
notification are produced by the same code the gateway path uses.

### `recheck_payments` *(modified)*

Now passes `settle_missing=True` — it is one of the two places where "not found"
has had time to mean "never happened".

### `seed_bootcamps` *(modified)*

Updated for the `CourseResource` / `CourseDiscussion` renames. **Not run** — the
database still holds zero bootcamp courses.

---

## Serializers

`CourseSerializer` has exactly **one** `to_representation`. It merges the
bootcamp profile, instructor roster, cover resolution, and resource/discussion
counts in that order.

This is load-bearing: a second `to_representation` added further down the class
body silently replaced the first (a class body keeps only the last definition of
a name), stripping `venue_name`, `days`, `starts_on`, `ends_on`, `status`,
`instructors` and the counts from every bootcamp response.
`test_bootcamps` went 68 → 4 passing. Do not add a second one.

`thumbnail_url` round-trips a storage name, not an absolute URL:
`to_representation` resolves via `media_src()`, `validate_thumbnail_url` strips
the `/media/` prefix back off before saving.

---

## Tests

| Module | Tests | Status |
| --- | ---: | --- |
| `test_course_discussions.py` *(new)* | 23 | OK |
| `test_course_resources.py` *(new)* | 15 | OK |
| `test_mark_paid.py` *(new)* | 5 | OK |
| `test_bootcamps.py` | 59 | OK |
| `test_course_batch2.py` | 21 | OK |
| `test_payments.py` | 22 | OK |

Run together: **162 tests, OK, 38.1 s.**

Notable coverage worth keeping:

- `test_model_resource_lesson_must_belong_to_its_course` — a resource cannot
  point at a lesson from a different course
- `test_patch_and_delete_are_owner_scoped`
- `test_detail_counts_resources_on_a_skill_course`
- `test_upload_kind_resource_refuses_a_video`
- `test_pending_payment_cannot_post` — `pending_payment` is not enough to write
- `test_like_and_unlike_are_idempotent`
- `test_hidden_reply_is_excluded_from_the_count`
- payments: gateway call measured outside any transaction; a settled payment is
  not asked about twice; three consecutive `NOT_FOUND` polls do not kill a row
- `test_enrollment_status_endpoint_reports_the_state_enroll_hides`

---

## Known gaps

- **Zero bootcamp courses.** `Course.COURSE_TYPE_CHOICES` includes `bootcamp`
  and the routes are wired, but the DB holds 9 academic + 18 skill. Every
  `resources/` call therefore answers
  `{"code":"COURSE_NOT_FOUND","detail":"Bootcamp not found."}`. Correct
  behaviour; `seed_bootcamps` has not been run.
- `bootcamp_for()` is now used only by the bootcamp-specific paths; the
  resource and discussion views have moved to `course_for()` /
  `require_course_manager`.
