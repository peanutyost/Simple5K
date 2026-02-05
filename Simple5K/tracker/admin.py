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


@admin.register(runners)
class RunnersAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'race', 'number', 'paid', 'tag', 'rfid_tag_hex')


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
