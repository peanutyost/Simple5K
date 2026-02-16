"""
URL configuration for Simple5K project.
"""

from accounts.views import (
    login_view,
    logout_view,
    register_view,
)

from django.conf import settings
from django.contrib import admin
from django.urls import path, re_path, include
from django.views.generic.base import RedirectView
from django.views.static import serve
from tracker.views import race_overview, race_list, race_countdown

urlpatterns = [
    path('', race_list),
    path('captcha/', include('captcha.urls')),
    path('admin/', admin.site.urls),
    path('tracker/', include('tracker.urls')),
    path('signup/', RedirectView.as_view(url='/tracker/signup/')),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    # path('register/', register_view, name='register'),
    path('races/', race_list, name='race-until'),
    path('race-countdown/', race_countdown, name='race-countdown'),
]

# Serve uploaded media only when DEBUG is True (e.g. local dev). In production, nginx serves /media/.
if settings.DEBUG:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    ]
