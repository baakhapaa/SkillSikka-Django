# Instructor analytics integration

Backend answer to `backend-ask-instructor-my-courses-2026-11-17.md`. Everything
in that ask is implemented as written, except the two points under
"Decisions" below.

## Existing contracts (unchanged)

`GET /api/v1/courses/?instructor=<id>`, course detail, reviews and lessons keep
their shapes. The owner still sees their drafts; other users do not. One fix:
`subject_name` and `grade_name` are now always present (`null` on skill and
premium courses). Before, the keys were missing on those courses.

## `GET /api/v1/courses/{id}/instructor-analytics/?period=7d|30d|90d|all`

| Case | Response |
|---|---|
| Course owner (drafts too) or admin | `200` |
| Any other user | `403 {"code": "NOT_COURSE_OWNER"}` |
| Unknown course | `404 {"code": "COURSE_NOT_FOUND"}` |
| Other `period` value | `400 {"code": "INVALID_PERIOD"}` |
| No `period` | Same as `30d` |

The response shape matches the ask exactly. Every metric follows its
definitions there; the notes below cover what the app needs to know.

- **Nulls.** `null` always means "not recorded" (keep the dash). `0` and
  `"0.00"` are real zeros. `avg_completion_percent` is null when the course has
  no lessons or no active/completed students. A retention row's
  `completion_percent` is null when there are no such students.
- **Watch time.** `watch_time_seconds` is null until the player has reported
  at least once for this course; after that, `0` is a real zero.
- **Sources.** `sources` is `[]` until some enrollment of this course carries a
  real source. After that it always holds four rows in this order: `direct`,
  `organic`, `social`, `unknown`. `share_percent` is null when there are no new
  enrollments in the period. `conversion_percent` is always null.
- **`all`.** The previous-period dates and every `delta_*` field are null.

## Decisions

1. **Window length.** A window is exactly N calendar days ending today, and
   the previous window is the N days before it. So `30d` on 2026-11-17 is
   2026-10-19 → 2026-11-17, and the previous window is 2026-09-19 → 2026-10-18.
   The example in the ask showed 2026-10-18 as the start, which is 31 days and
   doesn't match its own 30-day previous window. Dates are UTC (the server's
   time zone).
2. **When an enrollment became active.** There is no column for this. A paid
   enrollment's date is its first successful payment's confirmation time; a
   free one's is its enrollment time. `new_in_period` counts enrollments that
   are active or completed now, so one that was later cancelled is not counted.

## `POST /api/v1/lessons/{id}/progress/` (new, for the player)

```json
{ "watched_seconds": 30, "position_seconds": 124 }
```

- Send while a lesson is open: the seconds watched since the last report
  (1–120) and, optionally, the current position.
- Response: `{lesson_id, credited_seconds, total_watched_seconds, position_seconds}`.
- The server never adds more than the real time since this student's previous
  report (plus 5 seconds of slack), so `credited_seconds` can be lower than
  what was sent. Report every 15–30 seconds and on pause or close.
- Who may report: students who can open the lesson, the same rule as
  `POST /lessons/{id}/complete/`. Not enrolled: `403 NOT_ENROLLED`. Not a
  student: `403`. Bad numbers: `400`.

## `POST /api/v1/courses/{id}/enroll/` (new optional field)

```json
{ "source": "social" }
```

`direct`, `organic`, `social` or `unknown`; omitted means `unknown`, and any
other value returns `400`. Everything else about enrolling is unchanged.
