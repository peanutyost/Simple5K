from datetime import timedelta

from django.contrib import admin
from .models import race, runners, laps, Banner, ApiKey, RfidTag, SiteSettings, EmailSendJob

admin.site.register(ApiKey)


@admin.register(RfidTag)
class RfidTagAdmin(admin.ModelAdmin):
    list_display = ('tag_number', 'rfid_hex_short')
    ordering = ('tag_number',)
    search_fields = ('tag_number', 'rfid_hex')

    @admin.display(description='RFID hex')
    def rfid_hex_short(self, obj):
        if not obj.rfid_hex:
            return ''
        return obj.rfid_hex[:24] + '...' if len(obj.rfid_hex) > 24 else obj.rfid_hex


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


def _recompute_runner_times_from_laps(runner_obj):
    """Recompute total_race_time, chip_time, race_avg_speed, race_avg_pace from laps. Returns True if updated."""
    race_obj = runner_obj.race
    if not race_obj.start_time:
        return False
    final_lap = (
        laps.objects.filter(
            runner=runner_obj,
            attach_to_race=race_obj,
            lap=race_obj.laps_count,
        ).first()
    )
    if not final_lap:
        return False
    finish_time = final_lap.time
    # Gun time
    runner_obj.total_race_time = finish_time - race_obj.start_time
    # Chip time
    lap0 = laps.objects.filter(
        runner=runner_obj, attach_to_race=race_obj, lap=0
    ).first()
    chip_start = lap0.time if lap0 else race_obj.start_time
    runner_obj.chip_time = finish_time - chip_start
    # Pace and speed from gun time and race distance
    total_seconds = runner_obj.total_race_time.total_seconds()
    if total_seconds <= 0:
        return False
    kmh = (race_obj.distance / 1000) / (total_seconds / 3600)
    runner_obj.race_avg_speed = kmh * 0.621371  # mph
    avg_pace_seconds = ((total_seconds / 60) / (race_obj.distance / 1609.34)) * 60
    runner_obj.race_avg_pace = timedelta(seconds=avg_pace_seconds)
    runner_obj.race_completed = True
    runner_obj.save()
    return True


def _reassign_places_for_race(race_obj):
    """Set place for all finished runners in this race by total_race_time, per gender."""
    for gender in ('female', 'male'):
        finishers = list(
            runners.objects.filter(
                race=race_obj,
                race_completed=True,
                gender=gender,
                total_race_time__isnull=False,
            ).order_by('total_race_time')
        )
        for idx, r in enumerate(finishers, start=1):
            if r.place != idx:
                r.place = idx
                r.save(update_fields=['place'])


@admin.register(runners)
class RunnersAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'race', 'number', 'paid', 'tag', 'rfid_tag_hex')
    actions = ['recompute_times']

    @admin.action(description='Recompute times from laps')
    def recompute_times(self, request, queryset):
        updated = 0
        races_to_reassign = set()
        for runner in queryset:
            if _recompute_runner_times_from_laps(runner):
                updated += 1
                races_to_reassign.add(runner.race_id)
        for race_id in races_to_reassign:
            _reassign_places_for_race(race.objects.get(pk=race_id))
        self.message_user(
            request,
            f'Recomputed times for {updated} runner(s). Places updated for affected races.',
        )


@admin.register(laps)
class LapsAdmin(admin.ModelAdmin):
    list_display = ('runner', 'lap', 'time')


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'paypal_enabled', 'paypal_business_email', 'paypal_sandbox')
    list_editable = ('paypal_enabled', 'paypal_business_email', 'paypal_sandbox')


@admin.register(EmailSendJob)
class EmailSendJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'race', 'subject', 'status', 'error_message_short', 'created_at', 'updated_at')
    list_filter = ('status',)
    readonly_fields = ('created_at', 'updated_at', 'error_message')
    search_fields = ('subject', 'race__name')
    actions = ['reset_stuck_sending']

    @admin.display(description='Error')
    def error_message_short(self, obj):
        if not obj.error_message:
            return ''
        return obj.error_message[:80] + '…' if len(obj.error_message) > 80 else obj.error_message

    @admin.action(description='Reset stuck (Sending → Failed)')
    def reset_stuck_sending(self, request, queryset):
        stuck = queryset.filter(status=EmailSendJob.STATUS_SENDING)
        count = stuck.update(
            status=EmailSendJob.STATUS_FAILED,
            error_message='Reset: job was stuck in Sending. Re-send from the email page if needed.',
        )
        self.message_user(request, f'Reset {count} stuck job(s) to Failed.')
