from django.contrib import admin
from .models import race, runners, laps, Banner, ApiKey
# Register your models here.

admin.site.register(ApiKey)


@admin.register(race)
class RaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'status')
    fields = ('name', 'status', 'Entry_fee', 'date', 'distance', 'laps_count', 'max_runners',
              'number_start', 'scheduled_time', 'start_time', 'end_time', 'all_emails_sent',
              'min_lap_time', 'logo', 'notes')


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'subtitle', 'background_color', 'active')

    fields = ('title', 'subtitle', 'background_color', 'image', 'active')


@admin.register(runners)
class RunnersAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'race', 'number', 'rfid_tag_hex')


@admin.register(laps)
class LapsAdmin(admin.ModelAdmin):
    list_display = ('runner', 'lap', 'time')
