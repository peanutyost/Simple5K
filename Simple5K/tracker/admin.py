from datetime import timedelta

from django.contrib import admin
from .models import race, runners, laps, Banner, ApiKey, RfidTag, SiteSettings, EmailSendJob

@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'key_masked', 'created_at', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)
    readonly_fields = ('created_at', 'key')
    fields = ('name', 'key', 'created_at', 'is_active')

    @admin.display(description='Key')
    def key_masked(self, obj):
        if not obj.key:
            return '—'
        return obj.key[:10] + '…' if len(obj.key) > 10 else obj.key


@admin.register(RfidTag)
class RfidTagAdmin(admin.ModelAdmin):
    list_display = ('tag_number', 'rfid_hex')
    ordering = ('tag_number',)
    search_fields = ('tag_number', 'rfid_hex')
    fields = ('tag_number', 'rfid_hex')


@admin.register(race)
class RaceAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'status', 'date', 'scheduled_time', 'Entry_fee', 'distance', 'laps_count',
        'max_runners', 'number_start', 'start_time', 'end_time', 'min_lap_time',
        'all_emails_sent', 'notes', 'logo',
    )
    list_filter = ('status',)
    search_fields = ('name', 'notes')
    fields = (
        'name', 'status', 'Entry_fee', 'date', 'scheduled_time', 'distance', 'laps_count',
        'max_runners', 'number_start', 'start_time', 'end_time', 'min_lap_time',
        'all_emails_sent', 'notes', 'logo',
    )


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('title', 'subtitle', 'background_color', 'image', 'pages_display', 'active')
    list_filter = ('active', 'show_on_home', 'show_on_signup', 'show_on_results', 'show_on_countdown')
    search_fields = ('title', 'subtitle')
    fieldsets = (
        (None, {
            'fields': ('title', 'subtitle', 'background_color', 'image', 'active'),
        }),
        ('Show on pages', {
            'fields': ('show_on_home', 'show_on_signup', 'show_on_results', 'show_on_countdown'),
            'description': 'Check each page where this banner should appear. You can select multiple pages.',
        }),
    )


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
    list_display = (
        'first_name', 'last_name', 'email', 'race', 'number', 'age', 'gender', 'type',
        'shirt_size', 'tag', 'race_completed', 'total_race_time', 'chip_time',
        'race_avg_speed', 'race_avg_pace', 'place', 'notes', 'email_sent', 'paid',
        'signup_confirmation_sent', 'created_at',
    )
    list_filter = ('race', 'gender', 'type', 'paid', 'race_completed', 'signup_confirmation_sent', 'email_sent')
    search_fields = ('first_name', 'last_name', 'email', 'number')
    autocomplete_fields = ('race', 'tag')
    actions = ['recompute_times', 'mark_signup_email_sent', 'mark_results_email_sent']
    fields = (
        'first_name', 'last_name', 'email', 'age', 'gender', 'type', 'shirt_size', 'notes',
        'number', 'tag', 'race',
        'race_completed', 'total_race_time', 'chip_time', 'race_avg_speed', 'race_avg_pace', 'place',
        'email_sent', 'paid', 'signup_confirmation_sent', 'created_at',
    )
    readonly_fields = ('created_at',)

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

    @admin.action(description='Mark signup confirmation email sent')
    def mark_signup_email_sent(self, request, queryset):
        count = queryset.update(signup_confirmation_sent=True)
        self.message_user(request, f'Marked signup confirmation sent for {count} runner(s).')

    @admin.action(description='Mark results email sent')
    def mark_results_email_sent(self, request, queryset):
        count = queryset.update(email_sent=True)
        self.message_user(request, f'Marked results email sent for {count} runner(s).')


@admin.register(laps)
class LapsAdmin(admin.ModelAdmin):
    list_display = ('runner', 'attach_to_race', 'lap', 'time', 'duration', 'average_speed', 'average_pace')
    list_filter = ('attach_to_race',)
    search_fields = ('runner__first_name', 'runner__last_name', 'runner__number')
    autocomplete_fields = ('runner', 'attach_to_race')
    fields = ('runner', 'attach_to_race', 'lap', 'time', 'duration', 'average_speed', 'average_pace')


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'paypal_enabled',
        'signup_confirmation_timeout_minutes', 'site_base_url',
    )
    list_editable = ('paypal_enabled',)
    fields = (
        'paypal_enabled',
        'signup_confirmation_timeout_minutes', 'site_base_url',
    )


@admin.register(EmailSendJob)
class EmailSendJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'race', 'subject', 'body_short', 'status', 'error_message_short', 'created_at', 'updated_at')
    list_filter = ('status',)
    readonly_fields = ('created_at', 'updated_at', 'error_message')
    search_fields = ('subject', 'body', 'race__name')
    autocomplete_fields = ('race',)
    fields = ('race', 'subject', 'body', 'status', 'created_at', 'updated_at', 'error_message')
    actions = ['reset_stuck_sending']

    @admin.display(description='Body')
    def body_short(self, obj):
        if not obj.body:
            return ''
        return obj.body[:80] + '…' if len(obj.body) > 80 else obj.body

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
