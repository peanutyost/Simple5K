# Race Tracking System

A Django-based web application for managing and tracking races, runners, and lap times. Supports RFID timing, PayPal entry fees, bulk email, and a JSON API for timing systems.

## Features

### Race & Runner Management
- **Race management** — Create, edit, and list races with distance, laps, entry fee, scheduled time, max runners, and minimum lap time
- **Runner registration** — Public signup with age bracket, gender, shirt size, running/walking type; optional reCAPTCHA
- **Bib number assignment** — Assign numbers (with optional number start); auto-assign RFID tags by tag number
- **Lap time tracking** — Manual lap entry or automated via API (RFID); gun time and chip time (from first crossing)

### Timing & RFID
- **RFID tags** — Reusable tags linked to runners; assign by bib via UI or API
- **Record laps via API** — POST lap crossings by RFID + timestamp; minimum lap time and lap 0 (chip start) handling
- **Chip time vs gun time** — Gun time from race start; chip time from first crossing (or race start) to finish
- **API key authentication** — Generate keys in the UI for timing endpoints

### Payments & Email
- **PayPal integration** — Optional entry fee at signup; return/cancel/IPN handling; pay-later links in confirmation emails
- **Signup confirmations** — Email after signup (after payment or configurable timeout); background command `send_signup_confirmations`
- **Post-race emails** — Send individual race report emails to runners; bulk job queue with `send_race_emails` management command
- **Unpaid reminders** — Bulk email to unpaid runners with payment link via email queue

### Reports & PDFs
- **PDF reports** — Per-runner race report and race summary PDF generation
- **Completed races** — View historical race results and overview
- **Shirt size tracking** — Per-race shirt distribution view
- **Email list** — Export or manage runner emails per race

### Public & UI
- **Real-time race overview** — Current race progress and runner standings
- **Race list & countdown** — Upcoming races with countdown timers
- **Banner management** — Editable banners with per-page visibility (home, signup, results, countdown)
- **Site settings** — Toggle PayPal, set base URL, signup confirmation timeout

### Other
- **User accounts** — Login, registration; admin and API key generation require auth
- **Page view tracking** — Optional tracking snippet in `Simple5K/tracker/templates/tracker.html` (included in header)

## Installation

1. Clone the repository:
```bash
git clone [repository-url]
cd Simple5K
```

2. Create a virtual environment and activate it:
```bash
python -m venv venv
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables (see [Environment variables](#environment-variables) and `Simple5K/docs/ENV.md`). For local development, at minimum:
```bash
DEBUG=TRUE
ALLOWED_HOSTS=localhost,127.0.0.1
TRUSTED_ORIGINS=http://localhost:8000
```

5. Apply migrations:
```bash
python manage.py migrate
```

6. Create a superuser:
```bash
python manage.py createsuperuser
```

7. (Optional) Collect static files for production:
```bash
python manage.py collectstatic --noinput
```

## Usage

### Admin Features (Login Required)
- **Add/Edit Race** — Create or modify races (name, distance, laps, entry fee, date, scheduled time, min lap time, notes, logo)
- **List Races** — View all races with pagination
- **Race Start** — Start/stop race and track laps
- **Track Laps** — Record lap times manually or via RFID/API
- **View Runners** — List runners per race; add/edit runners; assign bib numbers and RFID tags
- **RFID Tags** — Manage reusable RFID tags; assign to runners by bib
- **Mark Runner Finished** — Manually mark a runner as finished when not using RFID
- **Statistics & PDFs** — Generate per-runner PDF reports and race summary PDFs
- **Select Race for Report** — Choose race and generate reports
- **Email List** — Queue bulk emails (race emails or unpaid reminders) to runners
- **Site Settings** — Enable/disable PayPal, set site base URL, signup confirmation timeout
- **Shirt View** — View shirt size distribution per race
- **Generate API Key** — Create API keys for timing/API access
- **Completed Races** — View completed race selection and overview

### Public Features
- **Race Overview** — Current race progress and standings (home)
- **Race List** — Upcoming races with countdown
- **Race Countdown** — Countdown for a specific upcoming race
- **Race Signup** — Register for a race (optional PayPal payment, reCAPTCHA)
- **Signup Success** — Confirmation after signup (and payment return/cancel)
- **Completed Race Overview** — Historical results for completed races

## Environment Variables

Configuration is via environment variables (e.g. `.env` with `django-dotenv`). See **`Simple5K/docs/ENV.md`** for the full list.

Summary:
- **Core:** `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS`, `TRUSTED_ORIGINS`
- **Database:** `DATABASE_ENGINE`, `DATABASE_NAME`, `DATABASE_USERNAME`, `DATABASE_PASSWORD`, `DATABASE_HOST`, `DATABASE_PORT`
- **Email:** `SMTP_HOST`, `SMTP_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`
- **PayPal:** `PAYPAL_BUSINESS_EMAIL`, `PAYPAL_SANDBOX`, `PAYPAL_CUSTOM_SECRET`, `PAYPAL_IPN_BASE_URL`

## API

The app exposes a JSON API for timing systems: record laps by RFID, update race start/stop, assign RFID to runners, list available races, and add/edit runners (session auth). Full details: **`Simple5K/docs/API.md`**.

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `api/record-lap/` | POST | API key | Record lap(s) by RFID and timestamp |
| `api/update-race-time/` | POST | API key | Start or stop a race |
| `api/create-rfid/` | POST | API key | Create RFID tag (number, rfid_tag, optional name) |
| `api/assign-tag/` | POST | API key | Assign RFID tag to runner (race + bib) |
| `api/available-races/` | GET | API key | List non-completed races |
| `api/add-runner/` | POST | Session | Create runner in a race |
| `api/edit-runner/` | POST | Session | Update runner fields |
| `generate-api-key/` | POST | Session | Create API key (HTML response) |

## Management Commands

- **`send_race_emails`** — Process queue: send post-race report emails to runners for completed races (run periodically, e.g. cron).
- **`send_signup_confirmations`** — Send signup confirmation emails to runners who have paid or passed the signup confirmation timeout (run periodically).
- **`reset_stuck_email_jobs`** — Reset email jobs stuck in "sending" state (e.g. after a crash).

## Docker

A Dockerfile is provided for production-style deployment:

```bash
docker build -t simple5k .
docker run -p 8000:8000 --env-file .env simple5k
```

The image runs migrations, `collectstatic`, and Gunicorn (see `Simple5K/start-prod-server.sh`). Set `DEBUG=FALSE` and provide `SECRET_KEY`, database, and other env vars as in `Simple5K/docs/ENV.md`.

## Models

- **Race** — Name, status, entry fee, date, distance, laps_count, max_runners, number_start, scheduled_time, start/end time, min_lap_time, notes, logo, all_emails_sent
- **Runners** — Name, email, age, gender, number, type (running/walking), shirt_size, race, tag (RFID), race_completed, total_race_time (gun), chip_time, place, paid, created_at, signup_confirmation_sent, email_sent, notes
- **Laps** — Runner, time, lap number, attach_to_race, duration, average_speed, average_pace
- **RfidTag** — tag_number, rfid_hex (reusable across runners)
- **Banner** — Title, subtitle, image, background_color, active, show_on_home/signup/results/countdown
- **ApiKey** — name, key, is_active
- **SiteSettings** — paypal_enabled, signup_confirmation_timeout_minutes, site_base_url (singleton)
- **EmailSendJob** — race, subject, body, unpaid_reminder, status (queued/sending/completed/failed)

## Views (Summary)

### Admin
- `RaceAdd`, `RaceEdit`, `ListRaces`, `race_start_view`, `runner_stats`, `select_race`, `view_shirt_sizes`, `select_race_for_runners`, `show_runners`, `add_runner`, `edit_runner`, `assign_numbers`, `rfid_tags_list`, `mark_runner_finished`, `completed_races_selection`, `get_completed_race_overview`, `email_list_view`, `select_race_for_report`, `race_summary_pdf_page`, `generate_runner_pdf_report`, `generate_race_summary_pdf_report`, `GenerateRaceReportView`, `site_settings_view`, `generate_api_key`

### API
- `record_lap`, `update_race_time`, `create_rfid`, `assign_tag`, `get_available_races`

### Public
- `race_overview`, `race_signup`, `signup_success`, `race_countdown`, `race_list`, `paypal_return`, `paypal_cancel`, `pay_entry`

## Forms

- **RaceForm** — Race creation/editing
- **SignupForm** — Runner registration (public)
- **LapForm** — Lap time recording
- **runnerStats** — Runner statistics/PDF generation

## Requirements

- Python 3.x
- Django
- See `requirements.txt`: asgiref, Django, sqlparse, tzdata, django-dotenv, gunicorn, mysqlclient, whitenoise, reportlab, pillow, django-simple-captcha, pytz

## Notes

- Set timezone and database settings in `Simple5K/settings.py` (or via env).
- Use strong `SECRET_KEY` and `DEBUG=FALSE` in production; see `Simple5K/docs/ENV.md`.
- Page view tracking: add tracking code in `Simple5K/tracker/templates/tracker.html`; it is included in the header on all pages.

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

GPL-3.0 License
