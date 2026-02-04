"""
Background worker that processes EmailSendJob queue: sends one email per runner
with throttling to stay under Microsoft SMTP limits (~30/min). Each email
includes an unmonitored-account footer.
"""
import threading
import time

# Throttle: seconds between each email (30/min = 1 every 2 sec)
EMAIL_SEND_INTERVAL_SECONDS = 2

# Footer appended to every email
EMAIL_FOOTER = "\n\n---\nThis is an unmonitored email account. Please do not reply."


def _process_one_job(job):
    from django.core.mail import send_mail
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
                send_mail(
                    subject=job.subject,
                    message=body,
                    from_email=from_email,
                    recipient_list=[email],
                    fail_silently=False,
                )
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
    from .models import EmailSendJob

    while True:
        job = None
        try:
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


_worker_started = False
_worker_lock = threading.Lock()


def process_queue():
    """
    Process all queued EmailSendJob entries (blocking). Use from management command
    or cron so emails are sent even when the in-process worker thread is not running.
    """
    from .models import EmailSendJob

    while True:
        job = (
            EmailSendJob.objects.filter(status=EmailSendJob.STATUS_QUEUED)
            .order_by("created_at")
            .first()
        )
        if not job:
            break
        job.status = EmailSendJob.STATUS_SENDING
        job.save(update_fields=["status"])
        try:
            _process_one_job(job)
        except Exception as e:
            job.status = EmailSendJob.STATUS_FAILED
            job.error_message = str(e)[:2000]
            job.save(update_fields=["status", "error_message"])


def start_email_worker():
    """Start the background email worker thread (idempotent)."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
    t = threading.Thread(target=_worker_loop, daemon=True)
    t.start()
