from django.contrib import admin
from .models import race, runners, laps
# Register your models here.

admin.site.register(race)
admin.site.register(runners)
admin.site.register(laps)
