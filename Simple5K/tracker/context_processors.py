from .models import SiteSettings


def site_settings(request):
    """Add SiteSettings singleton to template context so all pages can use it (e.g. background image)."""
    settings_obj = SiteSettings.get_settings()
    url = settings_obj.background_image_url
    # Use absolute URL so images load reliably (navbar logo, CSS background) from any base path or proxy.
    absolute_url = request.build_absolute_uri(url) if url and not url.startswith(('http://', 'https://')) else (url or '')
    return {
        'site_settings': settings_obj,
        'site_background_image_url': absolute_url or None,
    }
