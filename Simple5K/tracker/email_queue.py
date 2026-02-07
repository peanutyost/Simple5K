"""
Background worker that processes EmailSendJob queue: sends one email per runner
with throttling to stay under Microsoft SMTP limits (~30/min). Each email
includes an unmonitored-account footer.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

# Microsoft 365 SMTP (authenticated) limit is 30 messages per minute.
# Use 2 seconds between sends to stay safely under that (30/min).
EMAIL_SEND_INTERVAL_SECONDS = 2
MAX_EMAILS_PER_MINUTE = 30

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
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or settings.EMAIL_HOST_USER

        if getattr(job, "unpaid_reminder", False):
            from .views import _pay_link_for_runner

            recipient_runners = list(
                runners.objects.filter(race=race_obj, paid=False)
                .exclude(email__isnull=True)
                .exclude(email="")
                .select_related("race")
            )
            for runner in recipient_runners:
                body = (job.body or "").strip()
                pay_link = _pay_link_for_runner(runner)
                if pay_link:
                    body += f"\n\nIf you haven't paid yet, you can pay here: {pay_link}"
                body += EMAIL_FOOTER
                try:
                    conn = get_connection(fail_silently=False, timeout=EMAIL_TIMEOUT_SECONDS)
                    msg = EmailMessage(
                        subject=job.subject,
                        body=body,
                        from_email=from_email,
                        to=[runner.email],
                    )
                    conn.send_messages([msg])
                    conn.close()
                except Exception as e:
                    job.status = EmailSendJob.STATUS_FAILED
                    job.error_message = str(e)[:2000]
                    job.save()
                    return
                time.sleep(EMAIL_SEND_INTERVAL_SECONDS)
        else:
            recipient_list = list(
                runners.objects.filter(race=race_obj)
                .exclude(email__isnull=True)
                .exclude(email="")
                .values_list("email", flat=True)
                .distinct()
            )
            body = (job.body or "").strip() + EMAIL_FOOTER
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
            logger.exception("Email worker failed processing job: %s", e)
            if job is not None:
                try:
                    job.status = EmailSendJob.STATUS_FAILED
                    job.error_message = str(e)[:2000]
                    job.save(update_fields=["status", "error_message"])
                except Exception as save_err:
                    logger.exception("Failed to save job failure state: %s", save_err)
        time.sleep(5)


# How often to check for runners due a signup confirmation (same process as race emails worker)
SIGNUP_CONFIRMATION_CHECK_INTERVAL_SECONDS = 5 * 60  # 5 minutes

# Only send timeout confirmation to signups from the last 24 hours (ignore older ones)
SIGNUP_CONFIRMATION_MAX_AGE_HOURS = 24


def _signup_confirmation_loop():
    """Background loop: every SIGNUP_CONFIRMATION_CHECK_INTERVAL_SECONDS, send signup
    confirmations to runners who have not received one and are either paid or older than
    signup_confirmation_timeout_minutes (from Site Settings). Ignores signups older than
    24 hours. Stays under Microsoft SMTP limit (30/min) and claims runners in the same
    transaction so only one process sends to each runner (no duplicate emails).
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
            # Only consider signups from the last 24 hours (don't send to very old signups)
            cutoff_24h = timezone.now() - timedelta(hours=SIGNUP_CONFIRMATION_MAX_AGE_HOURS)
            # Cap batch size so we don't exceed MAX_EMAILS_PER_MINUTE in one burst;
            # we sleep EMAIL_SEND_INTERVAL_SECONDS between each, so 30/min is safe.
            batch_size = min(50, MAX_EMAILS_PER_MINUTE)
            with transaction.atomic():
                due = list(
                    runners.objects.filter(signup_confirmation_sent=False)
                    .filter(created_at__gte=cutoff_24h)
                    .filter(Q(paid=True) | Q(created_at__lte=cutoff))
                    .select_related('race')
                    .order_by('created_at')
                    .select_for_update(skip_locked=True)[:batch_size]
                )
                if due:
                    # Claim immediately so other worker processes don't pick the same runners
                    runner_ids = [r.id for r in due]
                    runners.objects.filter(id__in=runner_ids).update(signup_confirmation_sent=True)
            if due:
                from .views import send_signup_confirmation_email
                for runner in due:
                    try:
                        send_signup_confirmation_email(runner)
                    except Exception as e:
                        logger.exception("Signup confirmation email failed for runner id=%s: %s", runner.id, e)
                        runners.objects.filter(id=runner.id).update(signup_confirmation_sent=False)
                    time.sleep(EMAIL_SEND_INTERVAL_SECONDS)
        except Exception as e:
            logger.exception("Signup confirmation loop error: %s", e)
        finally:
            try:
                from django.db import connection
                connection.close()
            except Exception as e:
                logger.debug("Connection close in signup loop: %s", e)


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
