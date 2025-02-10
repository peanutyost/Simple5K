from django.contrib import admin
from .models import race, runners, laps, Banner
# Register your models here.

admin.site.register(race)
admin.site.register(runners)
admin.site.register(laps)


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'subtitle', 'background_color', 'active')

    fields = ('title', 'subtitle', 'background_color', 'image', 'active')
