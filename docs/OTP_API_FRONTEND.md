# SkillSikka OTP API — Frontend Integration Guide

Contract for the three OTP flows: **student signup**, **instructor signup**, and
**password reset**. Everything below was verified against the running backend on
2026-10-07 (all flows end to end, with real emails).

- **Base URL (dev):** `http://192.168.1.77:8000/api/v1`
- **Format:** JSON request and response bodies (`Content-Type: application/json`).
- **Auth:** none of the OTP endpoints need a token. Protected endpoints use
  `Authorization: Bearer <access>`.

---

## Rules that apply to every OTP

| Rule | Value |
|---|---|
| Length | exactly **4 digits**, `0000`–`9999` |
| Type | **always send as a JSON string** (`"0042"`, never `42`), leading zeros matter |
| Expiry | 10 minutes |
| Wrong guesses | 5 per code; after the 5th the code is dead even if correct later |
| New code | requesting a new code invalidates the previous one |
| Error message | wrong, expired, used-up and dead codes all return the same message, by design |

**Where codes arrive in dev:** the backend sends OTP emails to a shared Mailtrap
test inbox, not to the real address. Ask the backend team for access, or read the
code from the backend terminal if email is switched off. In production the code
goes to the user's real inbox.

---

## Error response shape — handle both forms

`detail` is sometimes a **string** and sometimes a **list with one string**,
depending on the endpoint. Normalise it in one helper:

```ts
function errorMessage(body: any): string {
  const d = body?.detail;
  if (Array.isArray(d)) return d[0];
  if (typeof d === 'string') return d;
  // field errors, e.g. { "new_password": ["This password is too common."] }
  const first = body && Object.values(body)[0];
  return Array.isArray(first) ? String(first[0]) : 'Something went wrong.';
}
```

Rate limit: anonymous requests are limited to **20 per minute per IP**. Over that
the server returns **429**; show "Too many attempts, wait a minute."

---

## Flow 1 — Student signup

### 1. Register

`POST /register/student/`

```json
{
  "email": "asha@example.com",
  "password": "Strong-pass-123",
  "confirm_password": "Strong-pass-123",
  "name": "Asha",
  "gender": "female",
  "dob": "2008-05-14"
}
```

- `gender`: `"male" | "female" | "other"`
- `dob`: `YYYY-MM-DD` or `DD/MM/YYYY`
- Optional: `phone_country_code`, `phone_number`, `location`; with
  `multipart/form-data` also `profile_photo` (JPG/PNG ≤ 5 MB) and
  `student_id_card` (JPG/PNG/PDF ≤ 10 MB).

**201**
```json
{
  "user": { "id": "41", "email": "asha@example.com", "name": "Asha", "role": "student",
            "verification_status": "not_applicable", "email_verified": false },
  "detail": "Verify your email to complete signup.",
  "email_verification_required": true
}
```
No tokens are returned here. **Go to the OTP screen.** The code has already been emailed.

**400**: field errors, e.g. `{ "email": ["A user with this email already exists."] }`.
A duplicate email also comes back as
`{ "code": "EMAIL_ALREADY_REGISTERED", "message": "...", "errors": {...} }`.

### 2. Verify OTP

`POST /register/student/verify-otp/`

```json
{ "email": "asha@example.com", "otp": "0427" }
```

**200**: the user is now logged in. Store the tokens; no separate login call is needed.
```json
{
  "detail": "Email verified successfully.",
  "user": { "id": "41", "email": "asha@example.com", "name": "Asha", "role": "student",
            "verification_status": "not_applicable", "email_verified": true },
  "tokens": { "refresh": "<jwt>", "access": "<jwt>" }
}
```

**400**: `{ "detail": "Invalid or expired OTP." }` covers a wrong, expired or used-up code,
an unknown email, or an already-verified account. Keep the user on the OTP screen and
show the resend option.

### 3. Resend OTP

`POST /register/student/resend-otp/`

```json
{ "email": "asha@example.com" }
```

**200, always the same response:**
```json
{ "detail": "If an eligible account exists and the resend cooldown has elapsed, a signup OTP has been sent." }
```
The server silently skips sending when:
- less than **60 seconds** have passed since the last code, or
- the account has had **10 codes in the last 24 hours**.

**UI:** disable the Resend button for 60 s after registering and after each resend,
with a countdown. Never tell the user "code sent" as a guarantee; say
"If your account is eligible, a new code is on its way."

---

## Flow 2 — Instructor signup

Same as students, with instructor URLs:

| Step | Endpoint |
|---|---|
| Register | `POST /register/instructor/` |
| Verify | `POST /register/instructor/verify-otp/` |
| Resend | `POST /register/instructor/resend-otp/` |

Register takes the same base fields. Optional instructor fields: `province_id`,
`district_id`, `municipality_id`, `school_id` (integers), `qualification`,
`subject_expertise`, `experience_years` (whole number 0–100). Multipart extras:
`cv_resume`, `certificates_and_recommendations` (multiple files).

Responses are identical in shape, with `"role": "instructor"`. After verification,
`verification_status` is `"pending"`: the instructor is logged in but still awaits
admin approval of their documents. That is a separate state from email verification.

---

## Login for an unverified account

`POST /login/` with `{ "email", "password" }`

If the email was never verified, the response is **400**:
```json
{ "detail": ["Verify your email before signing in."] }
```
**Handle it:** send the user to the OTP screen for their role, call the matching
`resend-otp` endpoint, and let them enter the new code.

Other login errors: `["Invalid email or password."]`, `["This account is inactive."]`.

**200**
```json
{ "user": { "id": "41", "email": "...", "name": "...", "role": "student",
            "verification_status": "not_applicable" },
  "tokens": { "refresh": "<jwt>", "access": "<jwt>" } }
```

---

## Flow 3 — Password reset (all roles)

### 1. Request a code

`POST /forgot-password/`

```json
{ "email": "asha@example.com" }
```

**200, always the same, whether or not the account exists:**
```json
{ "detail": "If an account exists with this email, a password reset OTP has been sent." }
```
There is no server cooldown here. Each request sends a fresh code and **kills the
previous one**, so only the newest email's code works. Still add a 60 s client-side
cooldown on the button.

### 2. Verify the code

`POST /forgot-password/verify-otp/`

```json
{ "email": "asha@example.com", "otp": "0427" }
```

**200**
```json
{ "detail": "OTP verified successfully.", "reset_token": "<opaque string>" }
```
Keep `reset_token` in memory only. It is valid for **10 minutes** and **one use**.

**400**
- `{ "detail": ["Invalid or expired OTP."] }`: note that it is a list here.
- `{ "otp": ["Enter exactly 4 numeric digits."] }`: bad format.

After 5 wrong tries the code is dead. Offer "Send a new code", which calls step 1 again.

### 3. Set the new password

`POST /forgot-password/reset/`

```json
{
  "reset_token": "<from step 2>",
  "new_password": "New-strong-pass-456",
  "confirm_password": "New-strong-pass-456"
}
```

**200**: `{ "detail": "Password reset successfully." }`

After success:
- **Every existing session for this account is signed out.** Stored refresh tokens
  stop working, and already-issued access tokens expire within 30 minutes.
- **Send the user to the login screen.** No tokens are returned.

**400**
| Body | Meaning | UI |
|---|---|---|
| `{ "new_password": ["This password is too common.", ...] }` | failed strength rules | show the messages under the field |
| `{ "confirm_password": ["Passwords do not match."] }` | mismatch | show under confirm field |
| `{ "detail": ["Invalid or expired reset token."] }` | token used, expired (>10 min) or tampered | restart the flow at step 1 |

Password rules: at least 8 characters, not too common, not entirely numeric, and
not too similar to the user's name or email. Validate length client-side and let
the server enforce the rest.

---

## Tokens

| Token | Lifetime | Use |
|---|---|---|
| `access` | 30 minutes | `Authorization: Bearer <access>` on protected calls |
| `refresh` | 7 days | `POST /token/refresh/` with `{ "refresh": "<jwt>" }` → `{ "access": "<jwt>" }` |

A **401** from `/token/refresh/` means the session is over: the user logged out,
reset their password, or the token expired. Clear stored tokens and go to login.

`GET /me/` returns the profile, including `email_verified`.

---

## Screen flow summary

```
Register ──201──▶ OTP screen ──verify 200──▶ store tokens ▶ Home
                     │  ▲
              400 ───┘  └── Resend (60 s countdown)

Login ──400 "Verify your email…"──▶ resend-otp ▶ OTP screen (above)

Forgot password ▶ enter email ▶ OTP screen ──200──▶ new password ──200──▶ Login
                                   │                    │
                         5 wrong ──┘ "Send new code"    └─ token error ▶ restart
```
