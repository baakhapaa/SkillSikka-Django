# ICT & AI Bootcamp integration audit

Audit date: 2026-10-27. Branch: `ict-ai-bootcamp`.
Base and unchanged HEAD: `ed3a2730e9cef6fbab41c5d06dabf8394b3f5531`.
Fetched `origin/main` matched the requested base. The starting working tree was clean.
**NOT COMMITTED. NOT PUSHED.**

## Architecture and reuse

Bootcamps are `Course(course_type="bootcamp")`. Course.instructor remains the required, non-nullable owner/lead FK. Existing Enrollment, Payment, LessonProgress, CourseReview, Certificate/criteria, lesson paywall, academic grade access, completion, streak/badge/notification hooks, My Learning and Home Feed are reused.

The audit inspected the current models, course/lesson/enrollment serializers and views, course access/pagination/schema helpers, instructor verification/photo helpers, seeds, course/Home/learning/review/interest/payment tests and payment implementation before editing. No parallel bootcamp application, enrollment system or payment system was added.

New tables: BootcampProfile, CourseInstructor (display roster), BootcampResource, BootcampDiscussion and DiscussionLike. Lesson adds nullable day_number. Course adds the bootcamp choice. Profile date/day constraints and roster/like uniqueness are in the database; bootcamp-only ownership and parent rules also have model clean validation and API enforcement.

## Authoring contract

Use POST `/api/v1/courses/`, then PATCH `/api/v1/courses/{id}/`.

```json
{
  "title": "ICT & AI Bootcamp",
  "course_type": "bootcamp",
  "is_paid": false,
  "is_published": true,
  "lead_instructor_id": 123,
  "instructors": [
    {"instructor": 123, "role": "lead", "order": 0},
    {"instructor": 456, "role": "coach", "order": 1}
  ],
  "bootcamp_profile": {
    "venue_name": "Sundarbazar",
    "days": 4,
    "starts_on": "2026-09-21",
    "ends_on": "2026-09-24",
    "status": "completed"
  }
}
```

Replace example user IDs with existing active verified instructors. The same lead must occur exactly once in the roster. Course.instructor is that user, never the requesting admin. lead_instructor_id is write-only. Missing/null lead: LEAD_INSTRUCTOR_REQUIRED (400). Missing/mismatched/multiple roster leads: LEAD_INSTRUCTOR_NOT_IN_ROSTER (400). Duplicate roster instructors and invalid/inactive/unverified instructors are rejected.

Course/profile/roster writes are atomic, including rollback tests for failures after Course/Profile persistence. PATCH need not resend an unchanged lead. Nested profile PATCH merges existing dates before validation, rejects invalid ranges/days, and cannot shrink days below existing lesson day numbers. Bootcamp subject and grade are null. Existing paid-course price rules apply. Changing between bootcamp and another course type is rejected to protect nested data consistency.

All bootcamp Course, Lesson, resource, profile and roster authoring is admin-only, including publishing, draft writes, deletion, roster-lead attempts and lesson moves. ADMIN_ONLY is HTTP 403 with detail `Only administrators can manage bootcamps.` The existing quiz/question/option mutation hooks also enforce this bootcamp restriction, including moving content into a bootcamp. Academic/skill instructor ownership rules remain. Admins can reach course creation; non-bootcamp creation retains the default draft behavior.

The legacy HTML CourseForm cannot supply a profile/roster and excludes bootcamp creation. Bootcamp authoring uses the nested Course API. No separate profile/roster endpoint is needed.

## Read contract and learning

GET `/api/v1/courses/?course_type=bootcamp` uses the existing count/next/previous/results pagination envelope. Bootcamp rows retain ordinary Course fields and add flat venue, days, dates, status, episode, short description, hero media, quality and view count, plus the display roster. Roster output id identifies the instructor user. Existing enrollment/review/lesson/duration annotations are reused. Detail adds resources_count and discussions_count; discussions_count counts visible top-level discussions.

Roster users/photos are loaded in one prefetch, only when bootcamps are present. Profiles use select_related. Academic/skill-only lists, My Learning and public instructor detail do not acquire an empty roster query.

Free bootcamp enrollment becomes active. Paid bootcamp enrollment becomes pending_payment and enters the unchanged existing payment flow. Academic enrollment still returns COURSE_NOT_ENROLLABLE. Duplicate and unpublished enrollment codes remain ALREADY_ENROLLED and COURSE_NOT_PUBLISHED.

The existing non-academic lesson paywall already supports bootcamps: metadata is visible, protected content is null without active/completed enrollment, preview content remains readable, and admin/canonical owner read behavior is retained. Pending/cancelled enrollment does not unlock content. Academic grade access remains unchanged. require_course_access already routes non-academic courses through enrollment; no payment guard change was needed there.

Lesson.day_number is optional, separate from section, and constrained to 1..profile.days when supplied for bootcamps. Lesson.order remains canonical. The lesson list accepts day_number filtering. is_completed is scoped to the requesting user and uses one bulk progress lookup per serialization context, on list and detail.

Course certificates include bootcamps using existing completed-enrollment and quiz criteria, with no separate issuance system. Reviews, progress and streak/badge side effects use the existing endpoints.

## Resources

GET/POST `/api/v1/courses/{course_id}/resources/`.
PATCH/DELETE `/api/v1/courses/{course_id}/resources/{resource_id}/`.

GET is an authenticated bare array ordered by order, pk. Students need active/completed enrollment. Published bootcamp resources are readable by authenticated instructors, and admins may read drafts. Mutations require admin. All lookups are scoped to the course URL. The serializer exposes id, course, section, title, file_format, file_url, file_size_bytes, order and created_at. All requested formats are supported. No upload or signed-URL infrastructure was added.

## Discussions

GET/POST `/api/v1/courses/{course_id}/discussions/`.
PATCH/DELETE `/api/v1/courses/{course_id}/discussions/{discussion_id}/`.
POST/DELETE `/api/v1/courses/{course_id}/discussions/{discussion_id}/like/`.

Authenticated non-enrolled users may read published bootcamp discussions. Student posting requires active/completed enrollment; instructors and admins may participate. Likes use the same participation access. Top-level rows are paginated with page/page_size and ordering whitelist -created_at, created_at, -likes_count. Default/invalid fallback is -created_at.

Author data uses the existing photo helper, safe grade labels, Instructor/Student/Administrator labels and null for other roles. Like count/state, ownership, visible reply count and inline replies are included. Replies are limited to one level, must belong to the same course, and are capped at 50 inline per thread using a sliced prefetch/window query. replies_count is the full visible count, including replies beyond that cap.

Normal users cannot see/interact with hidden rows or children of hidden threads. Admins can see them for moderation. Body is trimmed and required, maximum 2000 characters. Stable errors include BODY_REQUIRED, BODY_TOO_LONG, DISCUSSION_NOT_FOUND and NOT_ENROLLED. No fake lock state was introduced.

POST/DELETE like are idempotent, return 200 and current count/state, and use atomic transactions, row locking where supported and a unique constraint. Authors delete their own rows; admins delete any. Deleting a parent cascades replies and likes. Only admins PATCH is_hidden; body editing is unsupported.

## Home

Home adds bootcamps, limited to six published courses ordered by descending starts_on, then pk. All six existing Home keys remain. It uses Course card serialization and adds no Gemini/network dependency.

## Local seed results

`python manage.py seed_bootcamps` was run twice against the local database after migration. Counts were identical:

| Record | First run | Second run |
|---|---:|---:|
| Bootcamp courses | 2 | 2 |
| Profiles | 2 | 2 |
| Roster rows | 2 | 2 |
| Lessons | 34 | 34 |
| Resources | 22 | 22 |
| Top-level discussions | 14 | 14 |
| Replies | 4 | 4 |
| Likes | 2 | 2 |
| Enrollments | 1 | 1 |
| Progress rows | 2 | 2 |

Sundarbazar: 4 days, 2026-09-21..24, completed, 20 lessons across days 1..4, 14 resources, 10 threads. Palungtar: 7 days, 2026-11-16..22, upcoming, 14 lessons across days 1..7, 8 resources, 4 threads. Each has two replies and a real DiscussionLike. Each has a first lesson named Demo marked preview, populated durations, and a consistent canonical/roster lead.

Only one active verified instructor exists locally: Sundarbazar is seven instructors short of its target of eight, and Palungtar uses that same legitimate instructor. Five existing students were available; existing authors are reused across discussions. No accounts, passwords or payment-success records were created. student@skillsikka.com exists and has an active free Sundarbazar enrollment and exactly the first two lessons completed. The seed uses venue/date/profile identity so the shared course title does not collapse the two records.

**Seed resource URLs under example.com are demo placeholders and are not claimed to be downloadable production media. The CC0 flower video is sample media, not bootcamp footage. Frontend must replace these before production.**

## Migration, tests and performance

Migration `0046_lesson_day_number_alter_course_course_type_and_more` depends on 0045; it was inspected and applied locally. There is one core leaf and no pending schema changes.

Focused suite: `python manage.py test core.test_bootcamps --noinput --verbosity 1`: **68/68 passed**. This includes running the existing provider contract tests unchanged against a paid bootcamp, model/API validation, atomic rollback, permissions, learning, seeds, schema and query growth.

Regression command:

```text
python manage.py test core.test_course_sections core.test_course_batch2 core.tests.MyLearningTests core.tests.LearningCompatibilityTests core.tests.HomeFeedTests core.tests.PublicInstructorTests core.tests.CourseReviewTests core.tests.NotificationIntegrationTests core.test_learning_interests core.test_payments --noinput --verbosity 1
```

**158 run: 157 passed, one known baseline error**, PaymentAdminTests.test_payments_page_lists_and_filters: missing staticfiles manifest entry css/admin.css. No new failures remain. Unrelated static code was not changed. Existing assertions were updated only for the required Home key, one Home collection query, and one bulk lesson-completion query.

Force-authenticated APIClient SQL query counts:

| Path | Small fixture | Expanded fixture |
|---|---:|---:|
| Bootcamp list, 1 vs 20 courses | 3 | 3 |
| Detail, 2 vs 12 roster members | 2 | 2 |
| Curriculum, 1 vs 20 lessons | 3 | 3 |
| Discussions, 1 vs 20 threads with replies | 4 | 4 |
| Home, 1 vs 20 bootcamps | 10 | 10 |

Expanded discussion fixtures also verify 55 visible replies report count 55 while only 50 are inlined. Production authentication may add a constant cost; these tests specifically rule out per-row enrollment/progress/roster/photo/like/reply queries.

## Integrity and OpenAPI

Compared against the base: core/payments.py and core/payment_views.py have no diff. AST comparisons confirm payment initiation/verification/status/history API classes, payment serializers, and Payment/Enrollment/LessonProgress/CourseReview/Certificate model classes are unchanged. The only enrollment eligibility change is rejecting academic courses instead of accepting only skill. No shared payment guard change was needed. Provider requests, verification, callbacks, signatures, credentials and state machine remain untouched.

OpenAPI generation succeeds with explicit bootcamp card/detail and nested create/update input schemas, resources, discussions, likes, lesson day/completion fields, enrollment support, stable error descriptions and Home bootcamps. Schema tests pass. No bootcamp/discussion/roster diagnostics were emitted. Existing unrelated project-wide warnings/errors remain; the bootcamp status enum is named explicitly without altering unrelated warnings.

Django check passes, makemigrations --check --dry-run reports no changes, showmigrations core shows 0046 applied and one linear chain, and git diff --check passes. Temporary edit/schema/audit scripts and generated schema are removed before delivery.

## Changed files

- config/settings.py
- core/api_urls.py
- core/api_views.py
- core/bootcamp_serializers.py
- core/bootcamp_views.py
- core/course_access.py
- core/course_schema.py
- core/forms.py
- core/management/commands/seed_bootcamps.py
- core/migrations/0046_lesson_day_number_alter_course_course_type_and_more.py
- core/models.py
- core/serializers.py
- core/test_bootcamps.py
- core/test_course_sections.py
- core/tests.py
- docs/ict-ai-bootcamp-integration.md

The ignored local db.sqlite3 was migrated and seeded as requested. No secrets were modified or included.

The eight-instructor demo roster target is the sole data shortfall because only one eligible existing instructor is available. Production media is intentionally outside this demo seed. The pre-existing static manifest error and unrelated schema diagnostics remain as instructed. **NOT COMMITTED. NOT PUSHED.**
