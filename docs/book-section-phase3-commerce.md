# Book Section Phase 3

Flutter calls the routes below under `/api/v1/` with `Authorization: Bearer <access-token>`. Student and instructor email verification still applies. Amounts are decimal strings in NPR. Dates use ISO 8601. Book source locations remain private and the legacy `file_url` response stays empty.

## Catalogue and detail

`GET /ebooks/?search=geometry&category=Math&subject=1&grade=3&difficulty=beginner&pricing=free&min_rating=3&min_price=0&max_price=100&ordering=highest_rated&page=1&page_size=20`

All parameters are optional. Search matches title or author. Category is case-insensitive. Subject and grade are IDs. Difficulty accepts `beginner`, `intermediate`, or `advanced`. Pricing accepts `free` for explicit zero and `paid` for positive prices. Unpriced legacy books can appear in unfiltered results. Ordering accepts `latest` (default), `popular` (verified purchase count, then visible review count), or `highest_rated` (average, then visible review count). Invalid filters return 400. The catalogue keeps its existing array response unless `page` or `page_size` is provided. Page size defaults to 20 and is capped at 50.

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {"id": 12, "title": "Geometry", "author": "Sample Writer", "price": "0.00", "currency": "NPR", "average_rating": 4.5, "review_count": 2, "is_saved": true, "is_purchased": false, "has_reading_access": false, "reading_progress": null, "can_purchase": false, "can_review": false, "available_action": "get_free"}
  ]
}
```

`GET /ebooks/12/` returns a single book. Example response below includes the existing metadata and Phase 3 fields.

```json
{
  "id": 12,
  "title": "Geometry",
  "author": "Sample Writer",
  "author_photo_url": "",
  "description": "An introduction to geometry",
  "subject": 1,
  "subject_name": "Mathematics",
  "grade": 3,
  "grade_name": "Grade 3",
  "uploaded_by": 4,
  "uploaded_by_name": "Sample Writer",
  "cover_url": "",
  "file_url": "",
  "category": "Math",
  "difficulty": "beginner",
  "highlights": ["Worked examples"],
  "price": "0.00",
  "currency": "NPR",
  "file_format": "pdf",
  "published_at": "2026-11-18T00:00:00Z",
  "is_published": true,
  "created_at": "2026-11-18T00:00:00Z",
  "updated_at": "2026-11-18T00:00:00Z",
  "average_rating": 4.5,
  "review_count": 2,
  "is_saved": true,
  "is_purchased": false,
  "has_reading_access": false,
  "reading_progress": null,
  "can_purchase": false,
  "can_review": false,
  "available_action": "get_free",
  "current_user_review": null
}
```

Ratings come from visible reviews. With no visible reviews the average and count are zero. `is_purchased` represents a currently valid paid entitlement. Free acquisitions and manager previews can set `has_reading_access` independently. Detail returns the viewer's review, including moderation status if hidden.

| Server action | Flutter behavior |
| --- | --- |
| `buy_now` | Show **Buy Now** only when checkout is enabled and `can_purchase` is true. Reserved for provider integration. |
| `get_free` | Show **Get Free**, call the acquisition endpoint, then refresh detail. |
| `read_now` | Open the authorized reader. |
| `continue_reading` | Resume using returned progress and chapter locator. |
| `unavailable` | Disable acquisition. Paid checkout currently returns this action. |

Show **Save** or **Unsave** independently on published books. This includes free books and paid books before purchase. Once checkout is enabled an unpurchased eligible paid book can show **Save** and **Buy Now** together.

## Save and saved books

`POST /ebooks/12/save/` accepts an empty body. Repeated requests return 200 with `{"is_saved": true}`. Drafts return 404. `DELETE /ebooks/12/save/` returns 204 with an empty body, including when already unsaved. It removes only the viewer's record.

`GET /ebooks/saved/` returns a page of published books with catalogue fields, sorted by most recently saved. An empty response is `{"count": 0, "next": null, "previous": null, "results": []}`. Saving grants no content access.

## Reviews

`GET /ebooks/12/reviews/?page=1` lists visible reviews on a published book. The page contains no account IDs or profile fields.

```json
{"count":1,"next":null,"previous":null,"results":[{"id":8,"rating":5,"review":"Clear examples.","is_hidden":false,"created_at":"2026-11-18T06:00:00Z","updated_at":"2026-11-18T06:00:00Z"}]}
```

`POST /ebooks/12/reviews/` with `{"rating":5,"review":"Clear examples."}` returns 201 and the review object. A valid acquisition is required (403 otherwise). Rating is an integer from 1 through 5. Optional review text is plain text, at most 2,000 characters. Duplicates return 409. A reviewer can `PATCH /ebooks/12/reviews/8/` with `{"rating":4}` (200 with updated object), or `DELETE /ebooks/12/reviews/8/` (204). Editing requires active entitlement. Deletion remains available to the author after loss of access. Other users receive 404. An administrator can hide or restore reviews in Book Commerce. Editing a hidden review leaves it hidden. Render text as plain text. Reviews that were valid at submission remain visible after refund unless moderated or deleted.

## Get Free, My Books, and reading

`POST /ebooks/12/get-free/` accepts an empty body. An explicitly zero-priced, published book must have at least one non-whitespace chapter or an existing, non-empty private source file. Empty chapters and missing/unavailable source files do not qualify. Source paths are checked inside private storage; storage paths are never returned. A successful first request returns 201 and repeats on an eligible book return 200. A null or positive price returns 409. Drafts return 404. A revoked grant cannot be restored by retrying.

```json
{"book":12,"source":"free","granted_at":"2026-11-18T06:00:00Z","has_reading_access":true}
```

`GET /ebooks/my-books/?status=in_progress` returns the viewer's active published acquisitions. Status accepts `all`, `not_started`, `in_progress`, or `completed`. Each result extends the catalogue book with acquisition date and completion status.

```json
{"count":1,"next":null,"previous":null,"results":[{"id":12,"title":"Geometry","is_purchased":false,"has_reading_access":true,"acquired_at":"2026-11-18T06:00:00Z","completion_status":"in_progress","available_action":"continue_reading","reading_progress":{"last_chapter_id":32,"position":{"paragraph":1},"completed_chapter_ids":[],"total_chapters":3,"completed_chapters":0,"overall_percentage":0,"last_read_at":"2026-11-18T06:20:00Z"}}]}
```

Completion is based on existing chapter completion records. Whole-file PDF progress can be resumed but has no whole-book completion event. Unpublishing hides acquisitions and suspends student access until republished. Administrator and current instructor-owner previews remain available.

For **Read Now**, use `GET /ebooks/12/chapters/` and open `GET /ebooks/12/chapters/32/`, or use `GET /ebooks/12/content/` for the authorized binary attachment. The contents response includes `reader_mode`, `chapters` and `progress`. For **Continue Reading**, use the locator in `reading_progress` or `GET /ebooks/12/progress/`.

```json
{
  "book":{"id":12,"title":"Geometry"},
  "reader_mode":"chapters",
  "chapters":[{"id":32,"chapter_number":1,"title":"Angles","estimated_reading_minutes":2,"pdf_page_start":null,"pdf_page_end":null,"is_completed":false}],
  "progress":{"last_chapter_id":32,"position":{"paragraph":1},"completed_chapter_ids":[],"total_chapters":1,"completed_chapters":0,"overall_percentage":0,"last_read_at":"2026-11-18T06:20:00Z"}
}
```

The example abbreviates book metadata. A protected attachment has a PDF or EPUB content type and a `Cache-Control: private, no-store` header. A user without reader access receives 403.

```json
{"last_chapter_id":32,"position":{"paragraph":1},"completed_chapter_ids":[],"total_chapters":3,"completed_chapters":0,"overall_percentage":0,"last_read_at":"2026-11-18T06:20:00Z"}
```

`PUT /ebooks/12/progress/` accepts e.g. `{"chapter_id":32,"position":{"paragraph":1},"completed":false}` and returns the updated progress object. `GET /reader/continue/` returns `{"books":[{"book":{"id":12,"title":"Geometry"},"progress":{"last_chapter_id":32,"position":{"paragraph":1},"overall_percentage":0}}]}` (nested objects abbreviated). It includes up to 20 accessible entries. The existing 403 response is retained for non-managers with no active acquisitions. Use the existing Phase 2 bookmark and reader settings contracts.

## Buy Now, direct checkout, payment status and history

`POST /ebooks/12/buy/` takes an empty body. The server owns all pricing. Eligible paid books currently respond with HTTP 503 and the body below. Drafts return 404; free, unpriced or unavailable books return 409. A disabled request creates no order and grants no access.

```json
{"code":"BOOK_CHECKOUT_DISABLED","detail":"Paid book checkout is currently disabled."}
```

No checkout URL or provider handoff is available. When a provider is connected, Flutter should use the approved server checkout response and refresh order detail after returning to the app. The final checkout URL contract awaits provider approval. Client redirects are never proof of payment.

`GET /book-orders/` returns an owner-scoped page of order objects, newest first. `GET /book-orders/41/` returns the viewer's order and current payment status; other accounts' order IDs return 404. Status values are `pending`, `processing`, `paid`, `failed`, `cancelled`, and `refunded`. `paid_at` is null until settlement and retained for history on refund. Free acquisitions appear in My Books.

```json
{"id":41,"reference":"0f27c526-1b04-44ac-b423-4480a2118ce8","book":12,"book_title":"Geometry","original_price":"100.00","amount":"100.00","currency":"NPR","status":"processing","created_at":"2026-11-18T06:10:00Z","paid_at":null}
```

## Payment-owner handoff

The existing course gateways and settlement resolve `Payment`, `Course`, and `Enrollment`. Book checkout requires approval for a book-specific adapter, merchant credentials and return URLs, webhook authentication, and sandbox verification. Existing course endpoints remain on the course flow.

1. After authenticated owner checks, call `prepare_book_order(user, book_id)` to lock the book, validate availability, and reuse or create one order with a server-side price snapshot. Keep the order reference as the provider idempotency key. Serialize provider initiation per order and persist the returned provider and provider reference before accepting settlement.
2. Authenticate callbacks using the provider-approved signature and replay rules. Treat redirects as signals to perform an authenticated server-side lookup. Verify merchant, order reference, provider session, immutable amount and currency, transaction identity, and final paid status. Reject mismatches. Use a server-derived currency only if the provider contract guarantees the verified merchant account is single-currency.
3. Pass verified evidence as `VerifiedBookPayment(order_reference, provider, provider_reference, transaction_id, amount, currency, status)` to `fulfill_verified_payment`. The service checks the stored identifiers and amounts again, atomically records paid status and grants access, rejects reused transaction identities, and treats matching repeated settlement as idempotent. Free and purchase grants remain separate audit records. A free acquisition is allowed while a paid order is pending; later settlement creates its own purchase grant without replacing the free grant. This function accepts trusted adapter evidence only and has no public route.
4. Apply a terminal verified refund using `refund_verified_order` with the matched original transaction and `status="refunded"`. It revokes only the grant associated with that order atomically, leaving any independent free grant valid. The provider owner must define partial refund, chargeback, late settlement, and reconciliation behavior before enabling checkout. Publish and test provider callbacks in its sandbox before making **Buy Now** available.

The dashboard supports read-only order and entitlement inspection, verified purchase counts and revenue excluding refunded orders, and review moderation. Any future administrative change to an entitlement requires an explicitly authorized, audited action.
