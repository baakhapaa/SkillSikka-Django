# Search integration

Two calls power the Search screen. Both need a signed-in user (any role).

## Before typing: `GET /api/v1/search/discover/`

```json
{
  "trending_searches": ["Python", "CSS Grid", "React Hooks"],
  "popular_courses": [ /* course cards */ ],
  "trending_creators": [ /* instructor cards */ ]
}
```

| Section | What it is |
|---|---|
| `trending_searches` | Up to 6 strings for the chips. Tap a chip to search that text. |
| `popular_courses` | Up to 10 published courses: most new students in the last 30 days first, then by rating. The same card as Home (`title`, `thumbnail_url`, `average_rating`, `level`, `is_enrolled`, …). |
| `trending_creators` | Up to 10 verified instructors: most new students in the last 30 days first, then by rating. The same shape as `GET /instructors/top/` (`id`, `name`, `profile_photo_url`, `qualification`, `total_students`, …). Open a profile with `GET /instructors/{id}/`. |

How Trending Searches are chosen:
- A term trends only after **2 or more different people** searched it in the
  last 7 days **and** it found something. One person's typo or a rude word
  never reaches other people's screens.
- Until there is enough search history, the list is filled with the real
  topics that have the most published courses. It can be shorter than 6, or
  empty when there are no courses with a topic. Hide the section when it is
  empty.

There is no `@handle` on users. Show `name` under the avatar.

## After typing: `GET /api/v1/search/?q=<text>`

| Param | Default | Notes |
|---|---|---|
| `q` | required | 1–100 characters. Every word must match somewhere. |
| `type` | `all` | `all`, `courses`, `creators` or `shorts` |
| `limit` | `10` | 1–50 per section |
| `offset` | `0` | Skip this many results, for "see all" pages |

```json
{
  "query": "react hooks",
  "type": "all",
  "counts": { "courses": 3, "creators": 1, "shorts": 2 },
  "courses":  [ /* course cards */ ],
  "creators": [ /* instructor cards */ ],
  "shorts":   [ /* Short objects, same as GET /shorts/ */ ]
}
```

- Only the sections asked for are returned. `type=courses` returns only
  `counts.courses` and `courses`.
- `counts` are the full totals, so use them for "See all (12)".
- What each section matches:
  - **Courses:** title, description, category, subject or instructor name.
    Published courses only. Title matches come first, then rating.
  - **Creators:** name, qualification or expertise. Verified instructors with
    at least one published course.
  - **Shorts:** title, caption (hashtags too), instructor or topic. Published
    Shorts only.
- Errors return `400` keyed by the field: an empty or too-long `q`, an unknown
  `type`, or an out-of-range `limit` or `offset`.

**Debounce typing** (about 300 ms) and don't send an empty `q`. The first
page of a search is recorded for Trending Searches (once per person per 10
minutes). Later pages are not recorded.
