from django.core.management.base import BaseCommand
from tracker.models import race, runners, laps
from tracker.views import send_race_report_email
import time


class Command(BaseCommand):
    help = 'Send emails to runners after the race has completed.'

    def handle(self, *args, **options):
        races_to_send = race.objects.filter(status='completed', all_emails_sent=False).order_by('date')
        for race_obj in races_to_send:
            race_obj.all_emails_sent = True
            race_obj.save()
            runners_list = runners.objects.filter(race=race_obj, email_sent=False).order_by('place')
            if runners_list:
                for runner in runners_list:
                    start_time = time.time()
                    if laps.objects.filter(runner=runner, attach_to_race=race_obj).exists():
                        print(f"Sending email to {runner.first_name} {runner.last_name}")
                        send_race_report_email(runner.pk, race_obj.pk)
                        runner.email_sent = True
                        runner.save()

                    end_time = time.time()
                    iteration_time = end_time - start_time
                    if iteration_time < 2.1:
                        time.sleep(2.1 - iteration_time)
