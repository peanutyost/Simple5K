from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.cache import cache
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

# Login rate limit: max failed attempts per IP, window in seconds
LOGIN_RATE_LIMIT_COUNT = 5
LOGIN_RATE_LIMIT_WINDOW = 900  # 15 minutes


def _get_client_ip(request):
    """Get client IP, respecting X-Forwarded-For when behind a proxy."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def _login_rate_limit_key(ip):
    return f'login_fail:{ip}'


def _is_login_blocked(request):
    ip = _get_client_ip(request)
    key = _login_rate_limit_key(ip)
    count = cache.get(key, 0)
    return count >= LOGIN_RATE_LIMIT_COUNT


def _record_login_failure(request):
    ip = _get_client_ip(request)
    key = _login_rate_limit_key(ip)
    try:
        count = cache.get(key, 0) + 1
        cache.set(key, count, LOGIN_RATE_LIMIT_WINDOW)
    except Exception:
        pass


def _clear_login_failures(request):
    ip = _get_client_ip(request)
    cache.delete(_login_rate_limit_key(ip))


def register_view(request):
    form = UserCreationForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect(reverse('login'))
    context = {"form": form}
    return render(request, "accounts/register.html", context)


def login_view(request):
    if request.method == "POST":
        if _is_login_blocked(request):
            form = AuthenticationForm(request)
            form.add_error(None, 'Too many failed login attempts. Please try again in 15 minutes.')
            return render(request, "accounts/login.html", {"form": form})
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            _clear_login_failures(request)
            nxt = request.GET.get("next", None)
            user = form.get_user()
            login(request, user)
            if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts=request.get_host()):
                return redirect(nxt)
            return redirect(reverse('tracker:race-overview'))
        _record_login_failure(request)
    else:
        form = AuthenticationForm(request)
    context = {
        "form": form
    }
    return render(request, "accounts/login.html", context)


def logout_view(request):
    if request.method == "POST":
        logout(request)
        return redirect(reverse('login'))
    return render(request, "accounts/logout.html", {})
