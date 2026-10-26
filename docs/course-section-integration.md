# Course section integration

`GET /api/v1/courses/` retains `course_type`, `subject`, `grade`, `instructor`,
`is_paid`, and `is_published` filters and adds `skill_category=<interest id>`.
Visibility remains published courses for students, published or owned courses for
instructors, and all courses for superusers / the `super_admin` role.

`search` matches title or description case-insensitively. Empty or whitespace-only
search adds no filter. `ordering` accepts exactly one of `created_at`, `title`,
`average_rating`, or `price`, with an optional leading `-`. Missing, empty, and
invalid values fall back to `-created_at`; `pk` breaks ties. Null ratings/prices
follow the configured database's null ordering.

This batch adds DRF PageNumberPagination only to the course list: `page` starts at 1,
`page_size` defaults to 20 and is capped at 50. Invalid/nonpositive page sizes use
the default. Invalid or out-of-range pages return DRF's 404 response. The response
is `{count, next, previous, results}`; links preserve query parameters. Other
list contracts are unchanged, including the existing Events pagination.

Course cards and detail include read-only `students_enrolled` (distinct students
with active/completed enrollments), `lessons_count`, `total_duration_seconds`
(sum of known durations; null if none are known), and request-specific
`is_enrolled` (active/completed). Counts use isolated subqueries so reviews and
enrollments cannot multiply lesson durations. Access uses Exists in course list,
detail, instructor detail, Home Feed, and My Learning. Serializer fallback access
checks use one bulk lookup per context, including lesson lists.

`Course.skill_category` is an optional LearningInterest id. It is intended for
skill courses; academic courses remain valid without it. `skill_category_name`
is read-only. The existing 12 interests remain; Drawing, Public Speaking, and
Music are appended idempotently. Coding is reused.

Lessons add optional nullable `section` (up to 200 characters) and
`duration_seconds` (nonnegative integer seconds), plus `is_preview` (default
false). Clients group curriculum by section. Existing ordering is preserved.
Course/lesson API writes keep existing ownership and publishing checks. The
existing admin CourseForm also exposes category.

For skill-course lessons, authenticated superusers, `super_admin` users, the
course owner, active/completed enrolled users, and preview readers receive
content. Batch 2 academic lessons instead require a published course and an active
student with a matching grade; academic previews do not bypass grade eligibility.
Owners/admins retain management access. Other readers receive metadata with `content_url` and `content_text`
set to null, for both list and detail and when filtering by academic topic.
Course visibility applies before serialization, including preview lessons.
Being another instructor or staff alone does not grant content access.
Legacy lessons linked only to a topic retain the existing academic grade access
rule: matching student grade, admin, or preview. Course-linked lessons always
use their course's access rules even when they also have a topic. Unattached legacy lessons
only expose content to admins. A serializer without an authenticated request
redacts content. This is response protection; external/public media URLs are
not converted into a new private file delivery system.

Run `python manage.py migrate`, then `python manage.py seed_courses` locally.
The command requires an existing instructor (or superuser fallback) as owner;
it creates no accounts or credentials. Stable owner/title, course/lesson-title,
student/course, and student/lesson lookups prevent duplicates. Existing rows are
preserved rather than overwritten. Keep demo titles stable when rerunning.

The catalogue creates six published free academic courses across grades 6–10,
four published skill courses in Coding, Drawing, Public Speaking, and Music,
one published empty course, and one unpublished draft. Python costs 1299.00.
Each of the ten teaching courses has three sections of three lessons, mixing
video/PDF/text, numeric durations, and a preview. Demo video/PDF URLs are public
sample assets; text lessons have course-specific practice prompts.

Up to five existing students supply review fixtures spanning ratings 1–5. Missing
reviewer identities are reported and never fabricated. If
`student@skillsikka.com` exists as a student, the command creates completed and
partially progressed free skill enrollments and a pending_payment Python
enrollment. Pending payment matches the existing enrollment API semantics,
grants no content access, and creates no payment or verification. Existing
enrollments/progress are preserved. Missing demo identity is reported.

Migration chain: existing `0042_coursereview` →
`0043_course_skill_category_lesson_duration_seconds_and_more` (four additive
fields) → `0044_seed_course_categories` (idempotent catalogue addition; reverse
is a no-op to preserve user associations).

## Batch 2

Academic courses use profile eligibility rather than enrollment. An authenticated,
active student can read protected content, complete lessons, read course progress,
and discover/take published quizzes when the course is published and their
StudentProfile grade matches its grade. A course without a defined grade permits
any active student. Preview flags do not bypass academic grade checks. Owners,
superusers, and super_admin users retain content/management access, including
unpublished courses, but management access alone does not create student progress
or attempts. Wrong-grade students receive null lesson content and 403 for protected
actions. Unpublished lesson curriculum remains hidden from normal readers.

Academic completion writes LessonProgress with no enrollment. Progress counts
only the authenticated user's completed lessons in the course; zero lessons is
0% and incomplete. No academic Enrollment is created. The existing grade-certificate
calculation already averages completion over published academic courses with
lessons; it is unchanged and now has reachable course-linked progress. Legacy
topic-only lesson rules remain unchanged. Skill learning, payment gating,
enrollment completion, and skill certificate rules remain unchanged. My Learning
retains its enrollment-based dashboard; academic progress uses the course progress
endpoint. Academic courses therefore continue reporting is_enrolled=false unless
historical enrollment data already exists.

GET `/api/v1/courses/{course_id}/quizzes/` returns an unpaginated metadata list:
id, title, description, pass_percentage, max_attempts, attempts_used,
best_percentage, is_passed. No questions or answers appear. Attempts used counts
completed attempts, matching the existing max-attempt rule; best percentage and
pass state also use completed attempts belonging to request.user. Best percentage
is a decimal string or null. No completed attempts means zero attempts and false
pass state. Skill access requires active/completed enrollment; academic access uses
the eligibility rule above. Owners/admins can inspect unpublished quizzes;
students only see published quizzes in published courses. QuizAttempt.enrollment
is nullable to support academic attempts without fake enrollments. Academic
submission rechecks eligibility in case publication/grade changes during an attempt.

Course action errors include a stable `code` and human-readable `detail`:
COURSE_NOT_FOUND (detail/actions/reviews), ALREADY_ENROLLED,
COURSE_NOT_ENROLLABLE, COURSE_NOT_PUBLISHED (enrollment/academic actions/quiz discovery),
NOT_ENROLLED (skill progress/completion/quizzes/review writes),
MAX_ATTEMPTS_REACHED, CERTIFICATE_NOT_ELIGIBLE, and REVIEW_EXISTS.
ACADEMIC_NOT_ELIGIBLE identifies an ineligible academic learner (403). This is
scoped error handling, not a global rewrite. Payment errors are unchanged.

Existing duplicate-review race protection and the one-review constraint are
retained; duplicate POST returns 400 with REVIEW_EXISTS. The existing reviews/me
route now supports GET alongside PATCH/DELETE, always selecting request.user's
review. Missing own review returns 404. Review writes retain enrollment eligibility,
integer 1–5 ratings, and identity-field rejection. Nested student contains only
id, name, profile_photo_url; the photo uses User.profile_photo_src and request
absolute-URL handling, or null when missing.

Course learning_outcomes and requirements are JSON lists defaulting to []. API and
admin form validation accept at most 50 strings, trim entries, reject blank entries,
reject nested/non-string values, and limit each entry to 500 characters. Existing
ownership and publishing checks control writes. The seed command fills empty
demo lists, preserves nonempty custom values, and creates one published knowledge
check per teaching course (one question, two options). Stable lookups retain
idempotency. No attempt or payment success fixtures are fabricated.

OpenAPI documentation registers the custom email-verified JWT class as HTTP Bearer,
documents the course/dashboard response bodies, preserves 201 for enrollment and
payment initiation, and describes the existing payment_url. Course list filters,
pagination, decimal price, nullable rating, integer review count, and nested review
author types are explicit. Home recommendations retain the deterministic/offline
implementation; no Gemini request was added. Generated schema files are temporary.

Migration 0045_course_learning_outcomes_course_requirements_and_more follows 0044:
two additive JSON fields and a nullable QuizAttempt enrollment foreign key. Existing
skill attempt enrollment links remain intact.
