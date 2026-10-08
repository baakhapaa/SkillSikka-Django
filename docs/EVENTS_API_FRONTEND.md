# Events API — answer to "Events Near You" ask (2026-10-08)

Answers to `backend-ask-events-near-you-2026-10-08.md`, and the contract to code
against. Everything here is implemented and covered by tests.

- **Base URL (dev):** `http://192.168.1.68:8000/api/v1`
- **Auth:** every endpoint needs `Authorization: Bearer <access>` (401 without).
- **Times:** UTC with a trailing `Z`. Convert to device local time (Nepal, +05:45) before display.

---

## Answers to your 12 questions

| # | Question | Answer |
|---|---|---|
| 1 | Real resource or static? | **Real resource.** Super admins create and publish events; students register. |
| 2 | Name | **`events`**, separate from `challenges`. |
| 3 | What "near you" means | **Both:** every in-person or hybrid event has a **district** (and usually a municipality). **Latitude/longitude are optional.** |
| 4 | Server or client, and the fallback | You send `near=true`, plus `lat`/`lng` if you have permission. The server tries, in order: **GPS within radius → user's profile municipality → profile district → all upcoming**. The response says which one it used in `near_scope`. No permission? Just omit `lat`/`lng`. |
| 5 | Pagination | **Paginated.** `{count, next, previous, results}`, default 20, `?page_size=` up to 50. With `near=true` there is also `near_scope`. |
| 6 | Display fields | Everything in your A4 list **except rating**. `rating` is always `null` for now: hide the stars. `ratings_count` is not sent. |
| 7 | Host | **A user (instructor), returned nested:** `{id, name, role, avatar_url}`. `role` is the subtitle the admin typed, defaulting to `"Instructor"`. `host` can be `null`. |
| 8 | Registration and capacity | `POST /events/{id}/register/`, `DELETE` to cancel. When full, you're **waitlisted** (`my_status: "waitlisted"`, still 201, not an error). When someone cancels, the first waitlisted person is promoted automatically. |
| 9 | Images | `cover_image_url` and `host.avatar_url` are **`null` when absent, never `""`**. They are **absolute, same-origin** (`http://192.168.1.68:8000/media/...`) and **public**: load them without the token. Built per request, so no length limit applies. |
| 10 | Drafts | **Never returned** by `/events/` or `/events/{id}/` (a draft gives 404). Admins see drafts only through `/admin/events/`. |
| 11 | Timezone | **UTC, ISO 8601 with `Z`**, e.g. `"2026-11-25T04:15:00Z"` = 10:00 AM NPT. |
| 12 | Saved events | **Server-side:** `POST`/`DELETE /events/{id}/save/`, list at `GET /events/saved/`, and `is_saved` on every event. |

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/events/` | List (home rail with `near=true`; "See All" without) |
| GET | `/events/{id}/` | Detail |
| POST | `/events/{id}/register/` | Register, or join the waitlist if full |
| DELETE | `/events/{id}/register/` | Cancel registration |
| POST | `/events/{id}/save/` | Bookmark |
| DELETE | `/events/{id}/save/` | Remove bookmark |
| GET | `/events/saved/` | Bookmarked events, newest first, paginated |

### `GET /events/` query parameters

| Param | Values | Default | Notes |
|---|---|---|---|
| `near` | `true` / `false` | `false` | Nearest-first with the fallback chain (Q4) |
| `lat`, `lng` | decimal degrees | — | Send both or neither. Also fills `distance_km` |
| `radius_km` | 0.1–200 | 25 | Only for the GPS step of `near=true` |
| `upcoming` | `true` / `false` | `true` | `true` = not yet ended (ongoing events included) |
| `format` | `in_person` / `online` / `hybrid` | — | |
| `district`, `municipality` | id | — | Same ids as `/locations/...` |
| `search` | text | — | Title, description, venue, city |
| `ordering` | `start_at` / `-start_at` / `distance` | `start_at` | `distance` needs `lat`/`lng`; ignored with `near=true` |
| `page`, `page_size` | int | 1, 20 | `page_size` max 50 |

Bad values (e.g. `lat=200`, `lat` without `lng`) → **400** with the field name as key.

**Home rail:** `GET /events/?near=true&lat=27.7172&lng=85.3240&page_size=10`
(drop `lat`/`lng` if location permission was denied).
**See All:** `GET /events/?page=1` plus any filters.

### List response

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "near_scope": "gps",
  "results": [ { …Event… } ]
}
```
`near_scope` (only with `near=true`): `"gps"` | `"municipality"` | `"district"` | `"all"`.
For example, the rail title could read "Events in your district" when it is `"district"`.

### Event object (list, detail, register responses)

```json
{
  "id": 41,
  "title": "Advanced Algebra & Calculus Masterclass",
  "description": "Dive deep into…",
  "highlights": ["Integration made practical", "Graphing techniques"],
  "cover_image_url": "http://192.168.1.68:8000/media/events/3f2a….png",
  "host": {
    "id": 7,
    "name": "Dr. Sarah Pakhrin",
    "role": "Mathematics Dept Head",
    "avatar_url": "http://192.168.1.68:8000/media/profile-photos/7/9c1e….jpg"
  },
  "start_at": "2026-11-25T04:15:00Z",
  "end_at": "2026-11-25T08:15:00Z",
  "format": "in_person",
  "venue_name": "Seminar Hall A, Tech Hub",
  "city": "Kathmandu, Nepal",
  "province_id": 3,
  "district_id": 27,
  "municipality_id": 271,
  "latitude": 27.7172,
  "longitude": 85.324,
  "distance_km": 3.4,
  "attendee_count": 120,
  "attendee_avatars": ["http://…/a1.jpg", "http://…/a2.jpg"],
  "capacity": 200,
  "spots_left": 80,
  "my_status": "none",
  "is_saved": false,
  "rating": null,
  "is_published": true,
  "created_at": "2026-10-01T09:12:00Z",
  "updated_at": "2026-10-05T11:40:00Z"
}
```

| Field | Null / empty when |
|---|---|
| `cover_image_url` | no cover uploaded → `null` |
| `host` | no host set → `null`; `host.avatar_url` → `null` without a photo |
| `municipality_id`, `district_id`, `province_id` | not set (online events may have none) |
| `latitude`, `longitude` | event has no coordinates |
| `distance_km` | you sent no `lat`/`lng`, or the event has no coordinates (1 decimal place) |
| `highlights`, `attendee_avatars` | `[]`, so hide the row |
| `capacity`, `spots_left` | `null` = unlimited |
| `rating` | always `null` for now |

- `attendee_count` counts **registered** people only, not the waitlist.
- `attendee_avatars` holds up to 4 photos of registered attendees who have a profile photo.
- `my_status` is `"none"` | `"registered"` | `"waitlisted"`.

### Register / cancel

`POST /events/{id}/register/` (no body)
- **201** + Event object, with `my_status` either `"registered"` or `"waitlisted"`.
- **200** + Event object if already registered or waitlisted. Safe to call twice.
- **400** `{"detail": ["This event has already ended."]}`
- **404** for an unknown or draft event.

`DELETE /events/{id}/register/` → **200** + Event object (`my_status: "none"`). Safe if not registered.

Use the returned object to refresh the button and counts. No extra GET is needed.

### Save

`POST /events/{id}/save/` → `{"event_id": 41, "is_saved": true}`
`DELETE /events/{id}/save/` → `{"event_id": 41, "is_saved": false}`

---

## Admin endpoints (super admin only, 403 for others)

| Method | Path |
|---|---|
| GET, POST | `/admin/events/` |
| GET, PATCH, DELETE | `/admin/events/{id}/` |
| GET | `/admin/events/{id}/registrations/` |

Create and update accept JSON or `multipart/form-data`. Fields:
- `title`
- `description`
- `highlights`: list, up to 10
- `cover_image`: JPG/PNG up to 5 MB
- `host_id`: must be an instructor
- `host_role`
- `start_at`, `end_at`: ISO 8601 with offset
- `format`
- `venue_name`, `city`
- `district_id`, `municipality_id`: province is filled automatically
- `latitude`, `longitude`: both or neither
- `capacity`: empty means unlimited
- `is_published`

Rules: in-person and hybrid events need a district; the end time can't be before the start.

---

## What did not change

- Location endpoints (`/locations/...`) still take no query params; that is a separate ask.
- `challenges` is unchanged and unrelated to events.
