# Simple5K Tracker — API Documentation

This document describes the JSON API for race timing, runner management, and RFID operations. All responses are JSON unless noted.

**Base URL:** Append these paths to your tracker app root (e.g. `https://yoursite.com/tracker/`).

---

## Authentication

### API key (timing & race endpoints)

These endpoints require a valid API key in the request header:

```http
X-API-Key: <your-api-key>
```

- **Generate a key:** Log in to the site and use **POST** `/generate-api-key/` with form body `name=<key-name>`. The key is shown once on the response page.
- Missing or invalid key returns `401` with `{"error": "Invalid API key"}`.

### Session (runner endpoints)

- **Add runner** and **Edit runner** require an authenticated session (log in via the web app). No `X-API-Key` header is used for these.

---

## Endpoints

### 1. Record lap(s)

Record one or more lap crossings (e.g. from a timing mat / RFID reader).

| | |
|---|---|
| **Method** | `POST` |
| **Path** | `api/record-lap/` |
| **Auth** | `X-API-Key` header |
| **Content-Type** | `application/json` |

**Request body:** A JSON array of lap objects. Each object:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `runner_rfid` | string | Yes | RFID tag hex value (e.g. from reader). Case-insensitive. |
| `race_id` | integer | Yes | Race ID. |
| `timestamp` | string | Yes | UTC time in ISO 8601 format: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (e.g. `2025-02-05T14:30:00.123456Z`). |

**Example request:**

```json
[
  { "runner_rfid": "A1B2C3D4", "race_id": 1, "timestamp": "2025-02-05T14:30:00.000000Z" },
  { "runner_rfid": "E5F6G7H8", "race_id": 1, "timestamp": "2025-02-05T14:30:01.500000Z" }
]
```

**Success response:** `200 OK`

```json
{
  "results": [
    { "runner_rfid": "A1B2C3D4", "status": "success" },
    { "runner_rfid": "E5F6G7H8", "status": "success" }
  ]
}
```

Each item in `results` may be:

- `{ "runner_rfid": "<hex>", "status": "success" }` — lap recorded or ignored (e.g. duplicate/too soon).
- `{ "runner_rfid": "<hex>", "status": "failed", "error": "<message>" }` — not recorded; see `error`.

**Possible per-lap errors:**

- `"Runner RFID required"` — missing `runner_rfid`
- `"Race ID required"` — missing `race_id`
- `"Timestamp is required"` — missing `timestamp`
- `"Tag not found"` — no RFID tag with that hex in the system
- `"No runner in this race has that tag"` — tag exists but not assigned to a runner in this race
- `"Race not found"` — invalid `race_id`

**Other errors:**

- `400` — Body not a JSON list: `{"error": "Laps data must be a list"}` or `{"error": "<exception message>"}`
- `405` — Method not allowed: `{"error": "Method not allowed"}`
- `401` — Missing/invalid API key

**Behavior notes:**

- Laps are rejected if they occur within the race’s **minimum lap time** (still returns `"status": "success"` for that item).
- When the final lap (lap number = race’s `laps_count`) is recorded, the runner is marked finished and place/speed/pace are set.

---

### 2. Update race time (start / stop)

Set the race start or end time and update status.

| | |
|---|---|
| **Method** | `POST` |
| **Path** | `api/update-race-time/` |
| **Auth** | `X-API-Key` header |
| **Content-Type** | `application/json` |

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `race_id` | integer | Yes | Race ID. |
| `action` | string | Yes | `"start"` or `"stop"`. |
| `timestamp` | string | Yes | UTC time, same format as record-lap: `YYYY-MM-DDTHH:MM:SS.ffffffZ`. |

**Example — start race:**

```json
{
  "race_id": 1,
  "action": "start",
  "timestamp": "2025-02-05T14:00:00.000000Z"
}
```

**Example — stop race:**

```json
{
  "race_id": 1,
  "action": "stop",
  "timestamp": "2025-02-05T15:30:00.000000Z"
}
```

**Success response:** `200 OK`

```json
{
  "status": "success"
}
```

**Behavior:**

- **start:** Sets `start_time`, sets status to `in_progress`. Only applied if current status is not already `in_progress` or `completed`.
- **stop:** Sets `end_time`, sets status to `completed`.

**Errors:**

- `400` — Invalid/missing body or `"Invalid action"`: `{"error": "<message>"}`
- `405` — `{"error": "Method not allowed"}`
- `401` — Invalid API key

---

### 3. Update RFID (assign tag to runner)

Assign an RFID tag to a runner in a race (by bib number).

| | |
|---|---|
| **Method** | `POST` |
| **Path** | `api/update-rfid/` |
| **Auth** | `X-API-Key` header |
| **Content-Type** | `application/json` |

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `race_id` | integer | Yes | Race ID. |
| `runner_number` | integer | Yes | Runner’s bib number in that race. |
| `rfid_tag` | string | Yes | RFID tag hex value. Case-insensitive. |

**Example:**

```json
{
  "race_id": 1,
  "runner_number": 42,
  "rfid_tag": "A1B2C3D4E5F6"
}
```

**Success response:** `200 OK`

```json
{
  "status": "success"
}
```

**Errors:**

- `400` — `{"error": "RFID tag not found with that hex value"}` or other validation/exception message
- `404` — `{"error": "Runner not found"}`
- `405` — `{"error": "Method not allowed"}`
- `401` — Invalid API key

---

### 4. Get available races

List races that are not completed (e.g. for timing UIs or race selection).

| | |
|---|---|
| **Method** | `GET` |
| **Path** | `api/available-races/` |
| **Auth** | `X-API-Key` header |

No request body or query parameters.

**Success response:** `200 OK`

```json
{
  "status": "success",
  "races": [
    {
      "id": 1,
      "name": "Spring 5K 2025",
      "status": "signup_open",
      "date": "2025-03-15",
      "scheduled_time": "09:00:00"
    }
  ]
}
```

- `date` is ISO date; `scheduled_time` is time (HH:MM:SS).
- Only races whose status is **not** `completed` are returned.

**Errors:**

- `400` — `{"error": "<exception message>"}`
- `405` — `{"error": "Method not allowed"}`
- `401` — Invalid API key

---

### 5. Add runner

Create a new runner for a race. Requires **session authentication** (logged-in user), not API key.

| | |
|---|---|
| **Method** | `POST` |
| **Path** | `api/add-runner/` |
| **Auth** | Session (login required) |
| **Content-Type** | `application/json` or form-encoded |

**Request body (JSON or form):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `race_id` | integer | Yes | Race ID. |
| `first_name` | string | Yes | Max 50 chars. |
| `last_name` | string | Yes | Max 50 chars. |
| `email` | string | Yes | Max 254 chars. |
| `age` | string | Yes | Age bracket: `0-12`, `12-17`, `18-34`, `35-49`, `50+`. |
| `gender` | string | No | `male` or `female`. |
| `number` | integer | No | Bib number; must be ≥ 0 if provided. |
| `type` | string | No | `running` or `walking`. |
| `shirt_size` | string | Yes | One of: `Kids XS`, `Kids S`, `Kids M`, `Kids L`, `Extra Small`, `Small`, `Medium`, `Large`, `XL`, `XXL`. |
| `notes` | string | No | Max 512 chars. |

**Example:**

```json
{
  "race_id": 1,
  "first_name": "Jane",
  "last_name": "Doe",
  "email": "jane@example.com",
  "age": "18-34",
  "gender": "female",
  "number": 101,
  "type": "running",
  "shirt_size": "Medium",
  "notes": ""
}
```

**Success response:** `200 OK`

```json
{
  "success": true,
  "runner": {
    "id": 42,
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com",
    "age": "18-34",
    "gender": "female",
    "number": 101,
    "type": "running",
    "shirt_size": "Medium",
    "paid": false
  }
}
```

**Error response:** `400`

```json
{
  "success": false,
  "errors": ["First name is required", "Valid age bracket is required"]
}
```

Possible validation errors include: missing/invalid `race_id`, name/email length, invalid age bracket/gender/type/shirt_size, invalid `number`, etc.

- `404` if `race_id` does not exist.
- `405` if method is not POST.

---

### 6. Edit runner

Update an existing runner. Requires **session authentication**, not API key.

| | |
|---|---|
| **Method** | `POST` |
| **Path** | `api/edit-runner/` |
| **Auth** | Session (login required) |
| **Content-Type** | `application/json` or form-encoded |

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `runner_id` | integer | Yes | Runner’s primary key (ID). |
| `first_name` | string | No | Max 50. |
| `last_name` | string | No | Max 50. |
| `email` | string | No | Max 254. |
| `age` | string | No | `0-12`, `12-17`, `18-34`, `35-49`, `50+`. |
| `gender` | string | No | `male`, `female`, or empty/null. |
| `number` | integer | No | Bib number; ≥ 0 or null. |
| `type` | string | No | `running`, `walking`, or empty. |
| `shirt_size` | string | No | Same values as add-runner. |
| `paid` | boolean | No | `true`/`false` (or `"true"`/`"false"`, `1`/`0`). |

Only include fields you want to change.

**Example:**

```json
{
  "runner_id": 42,
  "number": 102,
  "paid": true
}
```

**Success response:** `200 OK`

```json
{
  "success": true,
  "runner": {
    "id": 42,
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com",
    "age": "18-34",
    "gender": "female",
    "number": 102,
    "type": "running",
    "shirt_size": "Medium",
    "paid": true
  }
}
```

**Error response:** `400` — same `success: false` and `errors` array as add-runner.

- `404` if `runner_id` does not exist.
- `405` if method is not POST.

---

### 7. Generate API key (web)

Create a new API key. This is a **web view**, not a JSON API: it renders HTML and shows the new key once.

| | |
|---|---|
| **Method** | `POST` |
| **Path** | `generate-api-key/` |
| **Auth** | Session (login required) |

**Request:** Form-encoded body with `name=<key-name>`.

**Response:** HTML page displaying the new API key. The raw key value is only shown on this response; store it securely.

---

## Summary table

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `api/record-lap/` | POST | API key | Record lap(s) by RFID and timestamp |
| `api/update-race-time/` | POST | API key | Start or stop a race |
| `api/update-rfid/` | POST | API key | Assign RFID tag to runner (by race + bib) |
| `api/available-races/` | GET | API key | List non-completed races |
| `api/add-runner/` | POST | Session | Create runner in a race |
| `api/edit-runner/` | POST | Session | Update runner fields |
| `generate-api-key/` | POST | Session | Create API key (HTML response) |

---

## Timestamp format

All API timestamps are **UTC** in this format:

```
YYYY-MM-DDTHH:MM:SS.ffffffZ
```

Example: `2025-02-05T14:30:00.123456Z`

Use 6 decimal places for fractional seconds; the server parses with `%Y-%m-%dT%H:%M:%S.%fZ`.
