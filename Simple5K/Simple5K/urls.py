"""
URL configuration for Simple5K project.
"""

from accounts.views import (
    login_view,
    logout_view,
    register_view,
)

from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic.base import RedirectView
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
