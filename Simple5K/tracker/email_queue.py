"""
Background worker that processes EmailSendJob queue: sends one email per runner
with throttling to stay under Microsoft SMTP limits (~30/min). Each email
includes an unmonitored-account footer.
"""
import threading
import time

# Throttle: seconds between each email (30/min = 1 every 2 sec)
EMAIL_SEND_INTERVAL_SECONDS = 2

# SMTP connection timeout (seconds) so we don't hang forever
EMAIL_TIMEOUT_SECONDS = 60

# Jobs stuck in SENDING longer than this are reset to FAILED (worker may have stopped)
STUCK_SENDING_MINUTES = 15

# Footer appended to every email
EMAIL_FOOTER = "\n\n---\nThis is an unmonitored email account. Please do not reply."


def _process_one_job(job):
    from django.core.mail import get_connection, EmailMessage
    from django.conf import settings
    from django.db import connection

    from .models import EmailSendJob, runners

    try:
        race_obj = job.race
        recipient_list = list(
            runners.objects.filter(race=race_obj)
            .exclude(email__isnull=True)
            .exclude(email="")
            .values_list("email", flat=True)
            .distinct()
        )
        body = (job.body or "").strip() + EMAIL_FOOTER
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or settings.EMAIL_HOST_USER
        for email in recipient_list:
            try:
                conn = get_connection(fail_silently=False, timeout=EMAIL_TIMEOUT_SECONDS)
                msg = EmailMessage(
                    subject=job.subject,
                    body=body,
                    from_email=from_email,
                    to=[email],
                )
                conn.send_messages([msg])
                conn.close()
            except Exception as e:
                job.status = EmailSendJob.STATUS_FAILED
                job.error_message = str(e)[:2000]
                job.save()
                return
            time.sleep(EMAIL_SEND_INTERVAL_SECONDS)
        job.status = EmailSendJob.STATUS_COMPLETED
        job.save()
    except Exception as e:
        job.status = EmailSendJob.STATUS_FAILED
        job.error_message = str(e)[:2000]
        job.save()
    finally:
        connection.close()


def _worker_loop():
    from django.utils import timezone
    from datetime import timedelta

    from .models import EmailSendJob

    while True:
        job = None
        try:
            # Reset jobs stuck in SENDING (e.g. after server restart) so they don't stay stuck
            stuck_cutoff = timezone.now() - timedelta(minutes=STUCK_SENDING_MINUTES)
            EmailSendJob.objects.filter(
                status=EmailSendJob.STATUS_SENDING,
                updated_at__lt=stuck_cutoff,
            ).update(
                status=EmailSendJob.STATUS_FAILED,
                error_message="Reset: job was stuck in Sending (worker may have stopped). Re-send from the email page if needed.",
            )

            job = (
                EmailSendJob.objects.filter(status=EmailSendJob.STATUS_QUEUED)
                .order_by("created_at")
                .first()
            )
            if job:
                job.status = EmailSendJob.STATUS_SENDING
                job.save(update_fields=["status"])
                _process_one_job(job)
        except Exception as e:
            if job is not None:
                try:
                    job.status = EmailSendJob.STATUS_FAILED
                    job.error_message = str(e)[:2000]
                    job.save(update_fields=["status", "error_message"])
                except Exception:
                    pass
        time.sleep(5)


# How often to check for runners due a signup confirmation (same process as race emails worker)
SIGNUP_CONFIRMATION_CHECK_INTERVAL_SECONDS = 5 * 60  # 5 minutes


def _signup_confirmation_loop():
    """Background loop: every SIGNUP_CONFIRMATION_CHECK_INTERVAL_SECONDS, send signup
    confirmations to runners who have not received one and are either paid or older than
    signup_confirmation_timeout_minutes (from Site Settings). Throttled like race emails.
    Uses select_for_update so only one worker process sends to a given runner.
    """
    from django.utils import timezone
    from django.db.models import Q
    from django.db import transaction
    from datetime import timedelta

    from .models import runners, SiteSettings

    while True:
        try:
            time.sleep(SIGNUP_CONFIRMATION_CHECK_INTERVAL_SECONDS)
            site_settings = SiteSettings.get_settings()
            timeout_minutes = site_settings.signup_confirmation_timeout_minutes
            cutoff = timezone.now() - timedelta(minutes=timeout_minutes)
            with transaction.atomic():
                due = list(
                    runners.objects.filter(signup_confirmation_sent=False)
                    .filter(Q(paid=True) | Q(created_at__lte=cutoff))
                    .select_related('race')
                    .order_by('created_at')
                    .select_for_update(skip_locked=True)[:50]
                )
            if due:
                from .views import send_signup_confirmation_email
                for runner in due:
                    try:
                        send_signup_confirmation_email(runner)
                    except Exception:
                        pass
                    time.sleep(max(0, EMAIL_SEND_INTERVAL_SECONDS - 0.1))
        except Exception:
            pass
        finally:
            try:
                from django.db import connection
                connection.close()
            except Exception:
                pass


_signup_worker_started = False
_signup_worker_lock = threading.Lock()


def start_signup_confirmation_worker():
    """Start the background signup confirmation worker thread (idempotent). Same pattern as email worker."""
    global _signup_worker_started
    with _signup_worker_lock:
        if _signup_worker_started:
            return
        _signup_worker_started = True
    t = threading.Thread(target=_signup_confirmation_loop, daemon=True)
    t.start()


_worker_started = False
_worker_lock = threading.Lock()


def start_email_worker():
    """Start the background email worker thread (idempotent)."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()
