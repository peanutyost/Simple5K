from django.apps import AppConfig


class TrackerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tracker"

    def ready(self):
        import sys
        if 'migrate' in sys.argv or 'makemigrations' in sys.argv:
            return
        try:
            from .email_queue import start_email_worker, start_signup_confirmation_worker
            start_email_worker()
            start_signup_confirmation_worker()
        except Exception:
            pass
