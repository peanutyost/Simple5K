"""
Process the email queue: send all queued bulk emails to runners.
Run this manually or from cron (e.g. every 1–2 minutes) so emails are sent
even when the in-process worker thread is not running (e.g. some production setups).
"""
from django.core.management.base import BaseCommand
from tracker.email_queue import process_queue


class Command(BaseCommand):
    help = 'Process queued EmailSendJob entries (send bulk emails to runners).'

    def handle(self, *args, **options):
        process_queue()
        self.stdout.write(self.style.SUCCESS('Queue processed.'))
