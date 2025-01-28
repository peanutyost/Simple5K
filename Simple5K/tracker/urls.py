from django.urls import path
from django.contrib.auth.decorators import login_required
from .views import (
    laps_view,
    add_runner_view,
    race_start_view,
    race_overview,
    runner_stats,
    race_signup,
    signup_success,

)

app_name = 'tracker'
urlpatterns = [
    path('', race_overview, name='race-overview'),
    path('laps', laps_view, name='laps-record'),
    path('add-runner', add_runner_view, name='add-runner'),
    path('race-start', race_start_view, name='race-start'),
    path('runner-stats', runner_stats, name='runner-stats'),
    path('race_signup/', race_signup, name='race_signup'),
    path('signup_success/', signup_success, name='signup_success'),
]
