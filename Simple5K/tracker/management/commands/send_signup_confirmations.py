from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta

from tracker.models import runners, SiteSettings
from tracker.views import send_signup_confirmation_email


class Command(BaseCommand):
    help = (
        'Send signup confirmation emails to runners who have not received one yet: '
        'either they have paid (PayPal IPN) or the signup confirmation timeout has passed.'
    )

    def handle(self, *args, **options):
        site_settings = SiteSettings.get_settings()
        timeout_minutes = site_settings.signup_confirmation_timeout_minutes
        cutoff = timezone.now() - timedelta(minutes=timeout_minutes)
        due = runners.objects.filter(
            signup_confirmation_sent=False
        ).filter(
            Q(paid=True) | Q(created_at__lte=cutoff)
        ).select_related('race')
        count = 0
        for runner in due:
            send_signup_confirmation_email(runner)
            count += 1
            self.stdout.write(f"Sent signup confirmation to {runner.email} (runner id={runner.id})")
        if count == 0:
            self.stdout.write("No signup confirmations to send.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Sent {count} signup confirmation(s)."))
