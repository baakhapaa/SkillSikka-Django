# Task brief: paid course checkout with Khalti and eSewa

You are implementing paid-course checkout in the SkillSikka Flutter app. The backend
supports **Khalti** and **eSewa** through one flow. Everything below was verified against
the running server on 2026-10-08; the eSewa sandbox was exercised end to end.

**Environment: SANDBOX.** No real money moves. Use the test accounts in §6.

---

## 1. How it works (one flow for both gateways)

```
Course page ──"Buy"──▶ POST /courses/{id}/enroll/              (creates enrollment: pending_payment)
            ──────────▶ POST /courses/{id}/initiate-payment/    {provider: "khalti" | "esewa"}
                         ◀── { id, payment_url, status: "initiated", ... }
            open payment_url in an in-app WebView
                         user pays on Khalti / eSewa
                         gateway → our server, which verifies with the gateway itself
                         server redirects WebView to …/payments/complete/<ref>/?payment_id=12&status=successful
            app sees that URL ─▶ close WebView ─▶ GET /payments/{id}/ ─▶ show result, refresh course
```

**The server decides whether a payment succeeded by asking Khalti/eSewa directly.** The
app never reports success. Treat whatever the WebView URL says as a hint, and always
confirm with `GET /payments/{id}/`.

- **Base URL:** `http://192.168.1.68:8000/api/v1`
- **Auth:** the JSON endpoints need `Authorization: Bearer <access>`. The WebView pages do not.

---

## 2. Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/courses/{id}/enroll/` | Enroll first. For a paid course the enrollment starts as `pending_payment`. If it returns **400 `"You are already enrolled in this course."`**, that's fine: continue to initiate (e.g. the user enrolled earlier but never paid) |
| POST | `/courses/{id}/initiate-payment/` | Start a payment, get `payment_url` |
| GET | `/payments/{id}/` | Current status; also re-checks the gateway while `initiated` |
| POST | `/payments/verify/` | Force a re-check by reference (optional; same result as the GET) |
| GET | `/my-payments/` | Payment history |

### `POST /courses/{id}/initiate-payment/`

Request: `{"provider": "khalti"}` or `{"provider": "esewa"}`

**201**
```json
{
  "id": 12,
  "course": 5,
  "course_title": "Paid Physics",
  "enrollment": 31,
  "amount": "1500.00",
  "provider": "esewa",
  "transaction_reference": "9f883de3-f75a-4e11-9e5a-656692fb400e",
  "status": "initiated",
  "gateway_transaction_id": "",
  "created_at": "2026-10-08T09:30:00Z",
  "verified_at": null,
  "payment_url": "http://192.168.1.68:8000/api/v1/payments/esewa/checkout/9f883de3-…/"
}
```
- Khalti: `payment_url` is Khalti's own payment page.
- eSewa: `payment_url` is a server page that auto-submits to eSewa.
- **Open it the same way for both.**

**Errors**

| Status | Body | Show |
|---|---|---|
| 400 | `{"detail": ["You must enroll in this course before initiating payment."]}` | call enroll first, then retry |
| 400 | `{"detail": ["This enrollment is already active."]}` | already purchased: open the course |
| 400 | `{"detail": ["This course is free and does not require payment."]}` | no payment needed |
| 400 | `{"provider": ["\"x\" is not a valid choice."]}` | bug: send `khalti` or `esewa` |
| 502 | `{"detail": "Khalti requires an amount of at least Rs. 10."}` (or other gateway error) | "Payment service error, try again or use the other method" |
| 503 | `{"detail": "Khalti is not configured on the server."}` | hide or disable that option; offer the other |

> ⚠️ **Right now Khalti returns 503** until the backend adds a Khalti sandbox key.
> eSewa works today. Build both; just handle 503 gracefully.

### Payment object: `status` values

| `status` | Meaning | UI |
|---|---|---|
| `initiated` | Not finished, or the gateway hasn't confirmed yet | "Payment pending…", with a Check again button |
| `successful` | Gateway confirmed; enrollment is now `active` | Success, open the course |
| `failed` | Not paid (expired, not found, or amount mismatch) | "Payment failed", with a Try again button that initiates a new payment |
| `cancelled` | User cancelled on the gateway | "Payment cancelled", with a Try again button |

`amount` is a **string** (`"1500.00"`): parse it as a decimal, never as a double.

---

## 3. The WebView (most important part)

1. Open `payment_url` in an **in-app WebView** (e.g. `webview_flutter`) with
   **JavaScript enabled**. The eSewa page auto-submits a form, and the gateways use JS.
2. Allow navigation to the external gateway domains (`*.khalti.com`, `*.esewa.com.np`).
3. In the navigation delegate, watch every URL. When it contains
   **`/api/v1/payments/complete/`**:
   - read `payment_id` and `status` from the query string;
   - **close the WebView** (don't render the page; it's only a fallback);
   - call `GET /payments/{payment_id}/` and use **that** status for the UI.
4. If the user closes the WebView themselves (back button), call `GET /payments/{id}/`
   anyway. The payment may have completed. If it is still `initiated`, show "pending" with
   Check again.

```dart
NavigationDecision onNav(NavigationRequest req) {
  final uri = Uri.parse(req.url);
  if (uri.path.contains('/api/v1/payments/complete/')) {
    final id = int.parse(uri.queryParameters['payment_id']!);
    Navigator.of(context).pop(id);            // close the WebView, return the id
    return NavigationDecision.prevent;
  }
  return NavigationDecision.navigate;
}
// After the WebView closes: final p = await api.get('/payments/$id/'); render p['status'].
```

**External browser instead of a WebView?** It works, but the app can't see the return URL.
Then call `GET /payments/{id}/` when the app resumes (`AppLifecycleState.resumed`).
A deep link (`skillsikka://payment-complete?payment_id=..&status=..`) can be switched on
server-side later; ask the backend team if you want it.

**Don't** use the Khalti or eSewa Flutter SDKs for this flow. The server has already
created the gateway order. Mixing in an SDK would create a second, unrelated order.

---

## 4. After success

- Re-fetch the course or enrollments. The enrollment is now `active`, `amount_paid` is set,
  and lessons unlock.
- The server also creates an in-app notification ("Payment successful").
- `GET /my-payments/` lists history, newest first (bare array, not paginated).

---

## 5. Edge cases to handle

- **Double taps on Buy:** each initiate creates a new payment. Disable the button while a
  request is in flight.
- **The user pays, but the network drops before the return:** the payment stays `initiated`
  on screen. `GET /payments/{id}/` asks the gateway again, so Check again fixes it.
- **Already purchased:** initiate returns 400 "already active". Treat it as success.
- **Khalti minimum:** Khalti refuses amounts under Rs. 10 (you get a 502 with that message).

---

## 6. Sandbox test accounts (no real money)

**eSewa** (works now)
- eSewa ID: `9711111111` (also …112, …113, …114)
- Password: `Nepal@123`
- Token / OTP: `123456`

**Khalti** (once the backend adds the sandbox key)
- Khalti ID: `9800000000` (also …001 to …005)
- MPIN: `1111`
- OTP: `987654`

To test: create a paid course in the admin (or ask the backend team for one), enroll, buy,
and pay with the test account. The course should unlock.

---

## 7. Acceptance checklist

- [ ] Buy flow: enroll if needed → initiate → WebView → result screen.
- [ ] Both Khalti and eSewa options; a 503 for one hides or disables it with a message.
- [ ] The WebView closes automatically on `/api/v1/payments/complete/` and the app confirms via `GET /payments/{id}/`.
- [ ] Closing the WebView manually still checks the status.
- [ ] `initiated` shows pending with Check again; `failed`/`cancelled` show Try again.
- [ ] On `successful`, the course unlocks without restarting the app.
- [ ] `amount` parsed as a decimal string.
- [ ] The Buy button can't be double-tapped.
