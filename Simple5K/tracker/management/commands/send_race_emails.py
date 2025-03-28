from django.core.management.base import BaseCommand, CommandError
from tracker.models import race, runners, laps
from tracker.views import send_race_report_email
import time


class Command(BaseCommand):
    help = 'Send emails to runners after the race has completed.'

    def handle(self, *args, **options):
        race_id = race.objects.filter(status='completed', all_emails_sent=False)
        if race_id:
            for race_obj in race_id:
                race_obj.all_emails_sent = True
                race_obj.save()
                try:
                    runners_list = runners.objects.filter(race=race_obj, email_sent=False).order_by('place')
                    if runners_list:
                        # this for loop allows less then 30 emails per minute as not to hit the office 365 limit.
                        # that is why there is a time calc and delay in there.
                        for runner in runners_list:
                            start_time = time.time()  # Record the start time of the iteration
                            if laps.objects.filter(runner=runner, attach_to_race=race_obj).exists():
                                print(f"Sending email to {runner.first_name} {runner.last_name}")
                                print(race_obj.name)
                                send_race_report_email(runner.pk, race_obj.pk)
                                runner.email_sent = True
                                runner.save()

                            end_time = time.time()  # Record the end time of the iteration
                            iteration_time = end_time - start_time

                            if iteration_time < 2.1:
                                time.sleep(2.1 - iteration_time)  # Wait to reach 2.1 seconds total

                except race.DoesNotExist:
                    raise CommandError("Race does not exist.")
