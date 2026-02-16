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
                    start_time = time.time()
                    if laps.objects.filter(runner=runner, attach_to_race=race_obj).exists():
                        logger.info("Sending email to runner pk=%s", runner.pk)
                        try:
                            send_race_report_email(runner.pk, race_obj.pk)
                            runner.email_sent = True
                            runner.save()
                        except Exception:
                            logger.exception("Failed to send email for runner pk=%s", runner.pk)
                            all_succeeded = False

                    end_time = time.time()
                    iteration_time = end_time - start_time
                    if iteration_time < 2.1:
                        time.sleep(2.1 - iteration_time)
            if all_succeeded:
                race_obj.all_emails_sent = True
                race_obj.save()
