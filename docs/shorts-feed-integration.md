# Shorts feed integration

Everything the Shorts screen draws now comes from `GET /api/v1/shorts/` (and
`GET /api/v1/shorts/<id>/`). The response is still a plain list, not paginated,
and every field that existed before is unchanged; the fields below are added.

## New response fields

| Field | Type | Screen element |
|---|---|---|
| `caption` | string (may be `""`) | Text under the video. Hashtags are inline (`#coding #webdev`). |
| `instructor_photo_url` | string (may be `""`) | Avatar next to the name. |
| `instructor_title` | string or null | Badge under the name (the instructor's `qualification`). |
| `topic`, `topic_name`, `topic_slug` | id / string, or null | A learning interest (Web Dev, Physics…). |
| `course`, `course_title` | id / string, or null | Course chip. Tap opens `/api/v1/courses/<course>/`. |
| `quiz`, `quiz_title` | id / string, or null | Quiz button. Hide the button when `quiz` is null. |
| `challenge`, `challenge_title` | id / string, or null | Challenge the Short belongs to. |

`course`, `quiz` and `challenge` are null for students until the target is
published (a quiz also needs its course published). The Short's owner and
admins always see the real values.

There is no `@handle` on users; show `instructor_name`.

## Tabs and search

All parameters combine and are optional.

| Query | Result |
|---|---|
| `?feed=for_you` | All Shorts, the student's learning interests first, then newest. Never empty while any Short exists. |
| `?feed=stem` | Shorts whose topic is Coding, Mathematics, Physics, Chemistry, Biology, Data Science, AI & ML, Web Dev, App Dev, Robotics or Electronics. |
| `?feed=challenge` | Shorts linked to a published challenge that has not ended. |
| `?topic=<slug>` | One topic, e.g. `?topic=web-dev`. Slugs come from `GET /api/v1/learning-interests/`. |
| `?search=<text>` | Case-insensitive match on title, caption or instructor name. Send `#` as `%23`. |

Any other `feed` value returns `400 {"feed": [...]}`. Without `feed` the order is
newest first, as before.

## Creating and editing (instructors)

`POST /api/v1/shorts/` and `PATCH /api/v1/shorts/<id>/` accept `caption`,
`topic`, `course`, `quiz` and `challenge` (ids, or `null` to clear). Rules, all
returning `400` keyed by the field:

- `topic` must be an active learning interest.
- `course` must be a course the instructor teaches; `quiz` must come from one.
- When both are set, the quiz must belong to the linked course. To move a Short
  to another course, send the new `course` with a matching `quiz` or `quiz: null`.
- `challenge` must be published.

Admins may link any course, quiz or challenge.

## Share

No backend call. Use the platform share sheet with the video link.
