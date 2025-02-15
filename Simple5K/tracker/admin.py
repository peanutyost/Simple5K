from django.contrib import admin
from .models import race, runners, laps, Banner
# Register your models here.

admin.site.register(race)


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'subtitle', 'background_color', 'active')

    fields = ('title', 'subtitle', 'background_color', 'image', 'active')

@admin.register(runners)  # Make sure this is the correct model name
class RunnersAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'race', 'number')


@admin.register(laps)
class LapsAdmin(admin.ModelAdmin):
    list_display = ('runner', 'lap', 'time')
