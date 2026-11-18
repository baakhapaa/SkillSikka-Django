# Instructor Profile integration

The Instructor Profile screen is one call:
`GET /api/v1/instructors/<instructor_id>/`. Every field that existed before is
unchanged; the fields below are added.

## Header

| Screen element | Field |
|---|---|
| Photo, name | `profile_photo_url`, `name` |
| Title under the name | `qualification` |
| Students / Courses / Rating | `total_students`, `total_courses`, `average_rating` (null when there are no reviews) |
| Biography | `bio` (string, `""` when not written; hide the section then) |
| Edit buttons on course cards | Show only when `is_me` is `true` |

## Course rows

All three lists hold the same course card objects as the `courses` list.

| Row | Field | Contents |
|---|---|---|
| Premium Courses | `premium_courses` | Published paid courses (`is_paid: true`), newest first. |
| Courses by this Instructor, See All (N) | `courses` | All published courses, newest first. Use `courses.length` for the count. |
| Popular Courses | `popular_courses` | Top 5 published courses: most students first, then highest rating, then newest. |

When the instructor opens their own profile (`is_me: true`), `courses` also
contains their unpublished drafts (`is_published: false`) so they can edit them.
`premium_courses`, `popular_courses` and the header numbers still show what
students see.

## Student Reviews

`recent_reviews` holds the 5 newest written reviews across all of the
instructor's courses:

```json
{
  "id": 12,
  "rating": 5,
  "review": "Prof. Shuvanga teaches in an incredibly visual and easy to understand manner.",
  "student": {"id": 4, "name": "Suman Shrestha", "profile_photo_url": null},
  "course": {"id": 7, "title": "The Art of Problem Solving"},
  "created_at": "...",
  "updated_at": "..."
}
```

- `rating` is a whole number from 1 to 5, so a single review card cannot show 4.8.
- Reviews with a rating but no text are left out of this list. They still count
  in the header's `review_count` and `average_rating`.

To show every review, call `GET /api/v1/instructors/<instructor_id>/reviews/`.
It is paginated: `?page=2&page_size=20` (max 50), and returns
`{count, next, previous, results}` with the same review objects.

## Instructor's own profile

- The instructor can always open their own profile, even before they are verified
  or have a published course. Everyone else gets `404` for such an instructor.
- Editing the biography: `PATCH /api/v1/me/` with `{"bio": "..."}` (up to 1000
  characters; `""` clears it). `GET /api/v1/me/` returns `bio` (null when empty).
  Only instructors can set it; anyone else gets `400 {"bio": ...}`.

## Share

No backend call. Use the platform share sheet.
