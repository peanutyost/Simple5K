from django.urls import path
from django.contrib.auth.decorators import login_required
from .views import (
    laps_view,
    add_runner_view,
    race_start_view,
    race_overview,
    
)

app_name = 'tracker'
urlpatterns = [
    path('', race_overview, name='race-overview'),
    path('laps', laps_view, name='laps-record'),
    path('add-runner', add_runner_view, name='add-runner'),
    path('race-start', race_start_view, name='race-start'),
]