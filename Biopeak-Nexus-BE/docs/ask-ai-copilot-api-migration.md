# Ask-AI / Biopeak Copilot frontend API migration

This guide covers the five frontend APIs used to open Ask-AI, load history, stream replies, and submit feedback.
`<baseURL>` is the configured Biopeak Nexus API base URL. Replace legacy profile identifiers with the selected Biopeak
profile UUID belonging to the authenticated customer.

## 1. Old and new APIs

| API                | Method | Old URL                                                                 | New URL                                                 |
|--------------------|--------|-------------------------------------------------------------------------|---------------------------------------------------------|
| Chat configuration | GET    | `https://api.metsights.com/profiles/:profile_id/features/biopeak-chat/` | `<baseURL>/profiles/:profile_id/copilot-chat/`          |
| Profile features   | GET    | `https://api.metsights.com/profiles/:profile_id/features/`              | `<baseURL>/profiles/:profile_id/features/`              |
| Chat history       | GET    | `https://biopeak-ai.metsights.com/chat/history/:session_id/`            | `https://ask-ai.biopeak.com/chat/history/:session_id/`  |
| Chat stream        | POST   | `https://biopeak-ai.metsights.com/chat/stream/:session_id/`             | `https://ask-ai.biopeak.com/chat/stream/:session_id/`   |
| Chat feedback      | POST   | `https://biopeak-ai.metsights.com/chat/feedback/:message_id/`           | `https://ask-ai.biopeak.com/chat/feedback/:message_id/` |

### Authentication and response handling

| New API                              | Header                                         | Response handling                                                                                                         |
|--------------------------------------|------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| Chat configuration, profile features | `Authorization: Bearer <Biopeak_access_token>` | Read the single `data` envelope. There is no `success` property.                                                          |
| History, stream, feedback            | `X-Api-Token: <token_from_copilot_chat>`       | Handle the direct history array, SSE stream, or feedback JSON respectively; no Biopeak `detail`/`data` envelope is added. |

The legacy inventory establishes the old URLs but does not fully specify their authentication or response contracts. The
new headers and examples below are the target integration contract; do not infer undocumented legacy fields.

## 2. Flow every time Ask-AI opens

1. Select the customer's Biopeak profile UUID. Profile features can determine frontend visibility, but the profile flag
   alone does not override platform availability.
2. **Every time the frontend opens an Ask-AI session**, call `GET <baseURL>/profiles/:profile_id/copilot-chat/` with the
   Biopeak bearer token. Do this even if the frontend retains credentials from an earlier opening.
3. Read `data.session_id` and `data.token`. Registration is handled internally by this endpoint when needed; the
   frontend only calls the profile endpoint for session credentials.
4. Load history and send chat requests to `https://ask-ai.biopeak.com` using the returned session ID and `X-Api-Token`
   token.
5. Reuse that token during the open session. After a token-related `401`, call the profile endpoint again and use the
   returned token with the same session ID. A Biopeak authentication failure requires the normal Biopeak login/refresh
   flow.
6. When the selected profile changes, obtain that profile's credentials through its own endpoint before issuing chat
   requests. Keep credentials and displayed history associated with their profile; never combine one profile's token
   with another session.

Opening Ask-AI does not create a new conversation session each time. The saved session ID stays fixed; every successful
configuration request returns a fresh ASK-AI token. Biopeak does not store that token or return `expires_at`. ASK-AI
controls expiry, documented as 24 hours by default; earlier tokens remain valid until their individual expiry or
revocation. Do not infer an expiry timestamp or reuse the former one-hour Django token window.

## 3. Profile APIs

### Chat configuration

**Method:** `GET`  
**Old:** `https://api.metsights.com/profiles/:profile_id/features/biopeak-chat/`  
**New:** `<baseURL>/profiles/:profile_id/copilot-chat/`  
**Authentication:** `Authorization: Bearer <Biopeak_access_token>`

| Parameter    | Location | Required | Meaning                                                                |
|--------------|----------|----------|------------------------------------------------------------------------|
| `profile_id` | Path     | Yes      | Selected Biopeak profile UUID belonging to the authenticated customer. |

No request body is required. Query parameters are ignored. Both profile and platform Copilot availability must be
enabled.

**200 OK:**

```json
{
  "detail": "Chat session initialized.",
  "data": {
    "id": "<copilot_session_uuid>",
    "session_id": "<session_id>",
    "token": "<copilot_token>"
  }
}
```

Use `session_id` in history/stream paths and `token` in `X-Api-Token`. The `id` field is the Biopeak session record
UUID, not the chat service's session identifier.

| Error | Meaning / action                                                                                                                                                                       |
|-------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 401   | Missing or invalid Biopeak authentication; use the normal authentication flow.                                                                                                         |
| 403   | Customer permission denied or chat disabled. Disabled-chat detail: `Copilot chat is not enabled for this profile.`                                                                     |
| 404   | Profile missing or outside the authenticated customer's profiles. Detail: `Customer profile with this ID not found.`                                                                   |
| 503   | ASK-AI configuration, connectivity, or credential response failed. Show the failure and allow a later retry; do not substitute previously fetched credentials as a successful opening. |

Example service failure:

```json
{
  "detail": "ASK-AI token issuance is unavailable."
}
```

Other service failure details: `ASK-AI is not configured.`, `ASK-AI registration is unavailable.`,
`ASK-AI is unavailable.`, `ASK-AI returned an invalid response.`, `ASK-AI returned incomplete credentials.`,
`ASK-AI returned an invalid session ID.`, and `ASK-AI returned a mismatched session ID.` Existing session IDs are not
replaced on these failures.

**Frontend change:** Replace the legacy route, use the Biopeak profile UUID and bearer token, fetch credentials at every
opening, and read `data.session_id` / `data.token` without additional nesting. The prior Nexus implementation returned
`expires_at` and cached a locally issued token for one hour; the current response omits that field and returns a fresh
service-issued token.

### Profile features

**Method:** `GET`  
**Old:** `https://api.metsights.com/profiles/:profile_id/features/`  
**New:** `<baseURL>/profiles/:profile_id/features/`  
**Authentication:** `Authorization: Bearer <Biopeak_access_token>`

`profile_id` is a required path parameter: the selected Biopeak profile UUID belonging to the customer. No request body
or query parameters are defined for this frontend read.

**200 OK:**

```json
{
  "detail": "Details.",
  "data": {
    "is_copilot_chat_enabled": true,
    "is_stable": false,
    "enabled_tabs": [
      "reports",
      "analysis",
      "action_plan",
      "care_team",
      "wellness"
    ],
    "updated_at": "<ISO-8601 timestamp>"
  }
}
```

Allowed tab codes are `reports`, `analysis`, `action_plan`, `care_team`, `personalised_plan`, and `wellness`. The array
can be empty. Feature flags control visibility; this endpoint supplies no session credentials.

**Errors:** `401` for missing/invalid authentication, `403` for permission denial, and `404` for a profile not available
to the customer (`Customer profile not found`).

**Frontend change:** Replace the host and profile identifier, authenticate with Biopeak, and read flags from `data`.
When Ask-AI opens, call chat configuration regardless of previously fetched credentials. A true profile chat flag does
not guarantee that the platform has enabled chat.

## 4. ASK-AI chat APIs

### Chat history

**Method:** `GET`  
**Old:** `https://biopeak-ai.metsights.com/chat/history/:session_id/`  
**New:** `https://ask-ai.biopeak.com/chat/history/:session_id/`  
**Authentication:** `X-Api-Token: <copilot_token>`

`session_id` is required in the path and must match the session returned with the token. No request body or query
parameters are defined.

**200 OK:** A direct array of messages in chronological order. Empty history is `[]`. Example without a chart:

```json
[
  {
    "role": "user",
    "content": "Explain my latest report.",
    "additional_data": null
  },
  {
    "role": "assistant",
    "content": "Here is an explanation of your report.",
    "additional_data": null
  }
]
```

Each message has `role` (`user` or `assistant`), `content` (string), and `additional_data` (null when no chart is
associated). Chart-bearing messages use the following structure; the chart key and values are illustrative:

```json
{
  "role": "assistant",
  "content": "Here is the trend chart.",
  "additional_data": {
    "plot_dict": {
      "multi_charts": {
        "<chart_key>": {
          "chart": {
            "data": [
              {
                "type": "scatter",
                "mode": "lines",
                "name": "Trend",
                "visible": true,
                "x": [
                  "2026-10-01",
                  "2026-10-07"
                ],
                "y": [
                  1.0,
                  2.0
                ],
                "line": {
                  "color": "#2563eb"
                }
              }
            ],
            "layout": {
              "title": {
                "text": "Trend"
              },
              "xaxis": {
                "title": {
                  "text": "Date"
                }
              },
              "yaxis": {
                "title": {
                  "text": "Value"
                }
              }
            }
          },
          "group_df": "<serialized_dataframe_identifier>",
          "group_reference_df": "<serialized_reference_dataframe_identifier>"
        }
      }
    }
  }
}
```

Preserve Plotly figure fields, including optional trace `mode`, `name`, `fill`, and `fillcolor`, axis ranges, and layout
`updatemenus`. Each menu can include `buttons` (`args`, `label`, `method`), `direction`, `showactive`, `x`, and `y`. The
`y` field may be a numeric array or a Plotly binary-encoded object such as `{"dtype": "<dtype>", "bdata": "<base64>"}`.
`group_df` and `group_reference_df` provide serialized dataframe identifiers for grouping context.

**Errors:** Missing token header returns `422`; invalid, expired, revoked, or session-mismatched token returns `401`; an
unreachable upstream returns `503`. Upstream HTTP errors are propagated with their status and a `detail` containing the
upstream response text.

**Frontend change:** Replace the host, send `X-Api-Token`, retain direct-array handling, and support nullable chart
data. Renew through the profile endpoint on a token-related `401`.

### Chat stream

**Method:** `POST`  
**Old:** `https://biopeak-ai.metsights.com/chat/stream/:session_id/`  
**New:** `https://ask-ai.biopeak.com/chat/stream/:session_id/`  
**Headers:** `X-Api-Token: <copilot_token>`, `Content-Type: application/json`

`session_id` is required in the path and must match the token's session. No query parameters are defined.

| Body field | Required | Contract                                                                                                                                                                                                                     |
|------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `message`  | Yes      | String. The upstream reference documents 1–10,000 characters and HTML/XSS validation.                                                                                                                                        |
| `media`    | No       | Array or null. Each item requires string `type` and accepts nullable string `url` / `base64`. The upstream reference supports `image` / `audio` and instructs callers to supply either `url` or `base64` per item, not both. |

```json
{
  "message": "Explain my latest report."
}
```

Optional media example:

```json
{
  "message": "Explain this image.",
  "media": [
    {
      "type": "image",
      "url": "<image_url>"
    }
  ]
}
```

The public request body contains no `session_id`: ASK-AI inserts the path value when forwarding upstream. The gateway
validates a string message and media field types; stricter upstream rules should not be described as gateway validation.

**200 OK:** `text/event-stream`, forwarded unchanged without a JSON response envelope. Successful responses contain
status updates, token chunks, and one terminal done event:

```text
data: {"status":"Analyzing your query..."}

data: {"chunk":"Here is "}

data: {"chunk":"your explanation."}

data: {"done":true,"response":"Here is your explanation.","additional_data":null}

```

There may be multiple status updates and many chunks. `response` is the complete concatenated reply. When charts are
present, `additional_data` contains the same `plot_dict` structure documented for history. On failure, an error event
replaces the terminal done event:

```text
data: {"error":"<human-readable error message>"}

```

**Errors:** Missing header or invalid gateway payload returns `422`; invalid, expired, revoked, or session-mismatched
token returns `401`. Handle stream-level error events as failures. The upstream reference documents `400` for rejected
XSS patterns, but the gateway forwards upstream streaming error bytes inside its streaming response rather than
propagating the upstream HTTP status. Do not assume HTTP `200` means the reply completed successfully.

**Frontend change:** Replace the host in both the API wrapper and fetch/SSE hook, send `X-Api-Token`, keep `session_id`
in the URL, and retain SSE parsing and terminal/error handling. Renew credentials through the profile endpoint on a
token-related `401` before a reply starts; preserve the user's input rather than automatically replaying a partially
received reply.

### Chat feedback

**Method:** `POST`  
**Old:** `https://biopeak-ai.metsights.com/chat/feedback/:message_id/`  
**New:** `https://ask-ai.biopeak.com/chat/feedback/:message_id/`  
**Headers:** `X-Api-Token: <copilot_token>`, `Content-Type: application/json`

`message_id` is required in the path: use the identifier supplied by the existing chat flow. There is no session ID in
this route and no defined query parameter.

| Body field | Required | Contract                                  |
|------------|----------|-------------------------------------------|
| `rating`   | Yes      | `positive` or `negative`.                 |
| `comment`  | No       | Nullable string, maximum 2000 characters. |

```json
{
  "rating": "positive",
  "comment": "Helpful explanation."
}
```

**200 OK:** Returns upstream feedback JSON unchanged, without a Biopeak envelope. Its exact success fields are not
defined in the supplied reference or gateway; preserve existing response handling rather than introducing assumed
fields. The supplied history/SSE examples also do not define a `message_id` field, so this guide does not invent one.

**Errors:** Missing header or invalid body returns `422`; invalid, expired, or revoked token returns `401`; an
unreachable upstream returns `503`. Upstream HTTP errors are propagated with their status and a `detail` containing the
upstream response text. The gateway validates an active token without a session ID in the route.

**Frontend change:** Replace the host, send `X-Api-Token`, keep the message ID in the path, and submit the
rating/comment payload. Renew through the profile endpoint on a token-related `401`.

## 5. Migration review

Frontend review checklist:

- Use the selected Biopeak profile UUID for both profile APIs.
- Fetch configuration on every Ask-AI opening, including reopening with saved credentials.
- Separate Biopeak bearer authentication from ASK-AI `X-Api-Token` authentication.
- Read only one configuration `data` envelope and remove dependence on `expires_at`.
- Use returned `session_id`, not the Biopeak session record `id`, for history and streaming.
- Update both API-wrapper and SSE-hook chat hosts.
- Preserve direct history arrays, Plotly chart data, SSE terminal/error handling, and upstream feedback JSON.
- Handle disabled chat, unavailable profiles, service failures, and token renewal without mixing profile credentials.
