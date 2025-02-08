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
    select_race,
    view_shirt_sizes,
    select_race_for_runners,
    show_runners,
    RaceAdd,
    RaceEdit,
    ListRaces,
)

app_name = 'tracker'
urlpatterns = [
    path('', race_overview, name='race-overview'),
    path('race_add/', RaceAdd.as_view(), name='race-add'),
    path('race_edit/<int:pk>/', RaceEdit.as_view(), name='edit-race'),
    path('list_races/', ListRaces.as_view(), name='list-races'),
    path('laps', laps_view, name='laps-record'),
    path('add-runner', add_runner_view, name='add-runner'),
    path('race-start', race_start_view, name='race-start'),
    path('runner-stats', runner_stats, name='runner-stats'),
    path('signup/', race_signup, name='race-signup'),
    path('signup_success/', signup_success, name='signup-success'),
    path('select_race/', select_race, name='select_race'),
    path('shirt_view/<int:pk>/', view_shirt_sizes, name='view_shirts'),
    path('runners_view/<int:pk>/', show_runners, name='view_runners'),
    path('select_race_runners', select_race_for_runners, name='select_race_runners'),
]
