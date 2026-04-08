import logging
import time

from django.core.management.base import BaseCommand
from tracker.models import race, runners, laps
from tracker.views import send_race_report_email

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send emails to runners after the race has completed.'

    def handle(self, *args, **options):
        races_to_send = race.objects.filter(status='completed', all_emails_sent=False).order_by('date')
        for race_obj in races_to_send:
            runners_list = runners.objects.filter(race=race_obj, email_sent=False).order_by('place')
            all_succeeded = True
            if runners_list:
                for runner in runners_list:
                    if not laps.objects.filter(runner=runner, attach_to_race=race_obj).exists():
                        continue

                    # Atomically claim this runner — if another process already
                    # marked email_sent=True, claimed will be 0 and we skip.
                    claimed = runners.objects.filter(pk=runner.pk, email_sent=False).update(email_sent=True)
                    if not claimed:
                        logger.info("Email already claimed for runner pk=%s, skipping", runner.pk)
                        continue

                    start_time = time.time()
                    logger.info("Sending email to runner pk=%s", runner.pk)
                    try:
                        send_race_report_email(runner.pk, race_obj.pk)
                    except Exception:
                        logger.exception("Failed to send email for runner pk=%s", runner.pk)
                        # Revert the flag so the next run will retry
                        runners.objects.filter(pk=runner.pk).update(email_sent=False)
                        all_succeeded = False

                    elapsed = time.time() - start_time
                    if elapsed < 2.1:
                        time.sleep(2.1 - elapsed)
            if all_succeeded:
                race_obj.all_emails_sent = True
                race_obj.save()
