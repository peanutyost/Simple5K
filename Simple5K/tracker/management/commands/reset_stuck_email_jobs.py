from django.core.management.base import BaseCommand

from tracker.models import EmailSendJob


STUCK_MESSAGE = (
    "Reset: job was stuck in Sending (worker may have stopped). "
    "Re-send from the Send Email page if needed."
)


class Command(BaseCommand):
    help = (
        "Reset email jobs stuck in 'Sending' to 'Failed' so they are no longer stuck. "
        "Use after a server restart or if the background worker stopped mid-send."
    )

    def handle(self, *args, **options):
        stuck = EmailSendJob.objects.filter(status=EmailSendJob.STATUS_SENDING)
        count = stuck.count()
        if count == 0:
            self.stdout.write("No jobs stuck in Sending.")
            return
        stuck.update(
            status=EmailSendJob.STATUS_FAILED,
            error_message=STUCK_MESSAGE,
        )
        self.stdout.write(self.style.SUCCESS(f"Reset {count} stuck job(s) to Failed."))
