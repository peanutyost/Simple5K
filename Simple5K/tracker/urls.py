from django.urls import path

from .views import (
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
    assign_numbers,
    generate_api_key,
    record_lap,
    update_race_time,
    update_rfid,
    get_available_races,
)

app_name = 'tracker'
urlpatterns = [
    path('', race_overview, name='race-overview'),
    path('race_add/', RaceAdd.as_view(), name='race-add'),
    path('race_edit/<int:pk>/', RaceEdit.as_view(), name='edit-race'),
    path('list_races/', ListRaces.as_view(), name='list-races'),
    path('race-start', race_start_view, name='race-start'),
    path('runner-stats', runner_stats, name='runner-stats'),
    path('signup/', race_signup, name='race-signup'),
    path('signup_success/<int:pk>', signup_success, name='signup-success'),
    path('select_race/', select_race, name='select_race'),
    path('shirt_view/<int:pk>/', view_shirt_sizes, name='view_shirts'),
    path('runners_view/<int:pk>/', show_runners, name='view_runners'),
    path('select_race_runners', select_race_for_runners, name='select_race_runners'),
    path('assign_numbers/', assign_numbers, name='assign_numbers'),
    # API endpoints
    path('generate-api-key/', generate_api_key, name='generate-api-key'),
    path('api/record-lap/', record_lap, name='api-record-lap'),
    path('api/update-race-time/', update_race_time, name='api-update-race-time'),
    path('api/update-rfid/', update_rfid, name='api-update-rfid'),
    path('api/available-races/', get_available_races, name='api-available-races'),

]
