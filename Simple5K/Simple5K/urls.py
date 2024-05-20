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
from tracker.views import race_overview

urlpatterns = [
    path('', race_overview),
    path('admin/', admin.site.urls),
    path('tracker/', include('tracker.urls')),
    path('login/', login_view),
    path('logout/', logout_view),
    path('register/', register_view),
]
