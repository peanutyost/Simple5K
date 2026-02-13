from .models import SiteSettings


def site_settings(request):
    """Add SiteSettings singleton to template context so all pages can use it (e.g. background image)."""
    return {'site_settings': SiteSettings.get_settings()}
