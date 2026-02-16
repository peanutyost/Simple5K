import re

from .models import SiteSettings


def _sanitize_css_url(url):
    """Sanitize a URL for safe use inside a CSS url() value.
    Strips characters that could break out of url("...") and inject CSS."""
    if not url:
        return None
    # Only allow http/https URLs
    if not re.match(r'^https?://', url):
        # Relative URL from media storage — allow alphanumeric, slashes, dots, hyphens, underscores
        if not re.match(r'^[a-zA-Z0-9/._ -]+$', url):
            return None
    # Remove characters that can break out of CSS url("...") context
    # Specifically: ", ', ), (, ; and backslash
    if re.search(r'["\')(\;\\]', url):
        return None
    return url


def site_settings(request):
    """Add SiteSettings singleton to template context so all pages can use it (e.g. background image)."""
    settings_obj = SiteSettings.get_settings()
    url = settings_obj.background_image_url
    # Use absolute URL so images load reliably (navbar logo, CSS background) from any base path or proxy.
    absolute_url = request.build_absolute_uri(url) if url and not url.startswith(('http://', 'https://')) else (url or '')
    # Sanitize for safe CSS url() usage (prevents CSS injection)
    safe_url = _sanitize_css_url(absolute_url) if absolute_url else None
    return {
        'site_settings': settings_obj,
        'site_background_image_url': safe_url,
    }
