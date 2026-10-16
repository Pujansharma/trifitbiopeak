# Customer Account ePRD

Retrieve the authenticated customer's account identity and read-only contact details.

Requires a customer JWT: `Authorization: Bearer <token>`.

## Logical Flow

1. **Get customer account** — retrieve account details for the authenticated customer without selecting an individual profile.

## API Requests

### 1. Get customer account

Return the authenticated customer's account ID, contact email, phone and account timestamps.

**Method:** `GET`

**URL:** `<baseURL>/customers/account/`

No path parameters, query parameters or request body. The endpoint is read-only and does not use pagination.

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "019e20ea-5d37-73c3-a176-62c39253e532",
    "email": "abcd@email.com",
    "phone": "+91-9999998989",
    "date_joined": "2026-05-13T16:08:10.744088+05:30",
    "last_login": "2026-10-06T10:34:23.791959+05:30",
    "updated_at": "2026-10-06T10:14:36.403813+05:30"
  }
}
```

Read account details from `data`. `id` identifies the customer account, not an individual profile. `email` is the stored customer contact email, with no account-email fallback. `phone` is the account phone. `email`, `phone` and `last_login` can be null; timestamps use ISO 8601 with a timezone offset.

All returned fields are read-only. Names, gender, date of birth and image are not included in this response.
