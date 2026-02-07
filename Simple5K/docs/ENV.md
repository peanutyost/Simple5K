# Environment Variables — Simple5K

Use these in a `.env` file (with something like `python-dotenv` or your host’s env config) or set them in the shell / process manager.

---

## Core (security / host)

| Variable | Required | Default | Notes |
|----------|----------|---------|--------|
| **DEBUG** | No | `FALSE` | Set to `TRUE`, `1`, or `YES` for local development. Leave unset or `FALSE` in production. |
| **SECRET_KEY** | **Yes in production** | (insecure default) | Set a long random secret in production. Optional for local dev if `DEBUG=TRUE`. |
| **ALLOWED_HOSTS** | No | `localhost` | Comma-separated: `localhost,example.com,www.example.com`. |
| **TRUSTED_ORIGINS** | No | `http://localhost` | Comma-separated origins for CSRF (e.g. `https://example.com`). |

---

## Database

| Variable | Required | Default | Notes |
|----------|----------|---------|--------|
| **DATABASE_ENGINE** | No | `sqlite3` | e.g. `postgresql`, `mysql`. |
| **DATABASE_NAME** | No | `db.sqlite3` (in project dir) | DB name or path for SQLite. |
| **DATABASE_USERNAME** | For PostgreSQL/MySQL | — | DB user. |
| **DATABASE_PASSWORD** | For PostgreSQL/MySQL | — | DB password. |
| **DATABASE_HOST** | For PostgreSQL/MySQL | — | DB host. |
| **DATABASE_PORT** | No | — | DB port. |

---

## Email (signup confirmations, race emails)

| Variable | Required | Default | Notes |
|----------|----------|---------|--------|
| **SMTP_HOST** | No | `smtp.office365.com` | SMTP server. |
| **SMTP_PORT** | No | `587` | SMTP port. |
| **EMAIL_HOST_USER** | For sending mail | — | SMTP login (e.g. Microsoft 365 email). |
| **EMAIL_HOST_PASSWORD** | For sending mail | — | SMTP password or app password. |
| **DEFAULT_FROM_EMAIL** | No | — | From address; often same as `EMAIL_HOST_USER`. |

---

## PayPal

PayPal business email and sandbox mode are **only** configured via environment variables (not in the Settings page).

| Variable | Required | Default | Notes |
|----------|----------|---------|--------|
| **PAYPAL_BUSINESS_EMAIL** | For PayPal flow | `''` | PayPal account that receives payments. |
| **PAYPAL_SANDBOX** | No | `False` | Set `TRUE` or `1` for PayPal sandbox. |
| **PAYPAL_CUSTOM_SECRET** | No | same as `SECRET_KEY` | Optional separate secret for signing PayPal custom field. |
| **PAYPAL_IPN_BASE_URL** | No | — | Optional public base URL for IPN/return/cancel (e.g. ngrok URL for local testing). |

---

## Minimal setups

**Local development (SQLite, no mail/PayPal):**

```bash
DEBUG=TRUE
# SECRET_KEY optional when DEBUG=TRUE
ALLOWED_HOSTS=localhost,127.0.0.1
TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

**Production:**

```bash
DEBUG=FALSE
SECRET_KEY=your-long-random-secret-here
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
# Then add database and (if used) email + PayPal vars
```

**Production with PostgreSQL and email:**

```bash
DEBUG=FALSE
SECRET_KEY=your-long-random-secret-here
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
TRUSTED_ORIGINS=https://yourdomain.com

DATABASE_ENGINE=postgresql
DATABASE_NAME=simple5k
DATABASE_USERNAME=simple5k
DATABASE_PASSWORD=your-db-password
DATABASE_HOST=localhost
DATABASE_PORT=5432

EMAIL_HOST_USER=you@example.com
EMAIL_HOST_PASSWORD=your-smtp-password
DEFAULT_FROM_EMAIL=you@example.com

PAYPAL_BUSINESS_EMAIL=you@paypal.com
# PAYPAL_SANDBOX=TRUE only for testing
```

---

## New / changed with the security settings

- **DEBUG** — Default is now `FALSE`. For local dev you must set **DEBUG=TRUE** (or `1`/`YES`) if you want the app to run without setting `SECRET_KEY`.
- **SECRET_KEY** — Must be set in production (no reliance on the default secret).
- **ALLOWED_HOSTS** / **TRUSTED_ORIGINS** — Support multiple values as comma-separated strings (e.g. `host1.com,host2.com`).
