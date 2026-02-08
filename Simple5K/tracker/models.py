from django.db import models
from django.urls import reverse
import secrets


class race(models.Model):
    status_choices = (
        ('signup_closed', 'Sign Up Closed'),
        ('signup_open', 'Sign Up Open'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed')
    )

    name = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=status_choices)
    Entry_fee = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(auto_now=False, auto_now_add=False)
    distance = models.IntegerField()
    laps_count = models.IntegerField()
    max_runners = models.IntegerField(null=True, blank=True)
    number_start = models.IntegerField(null=True, blank=True)
    scheduled_time = models.TimeField(null=True, blank=True)
    start_time = models.DateTimeField(
        auto_now=False, auto_now_add=False, null=True, blank=True)
    end_time = models.DateTimeField(
        auto_now=False, auto_now_add=False, null=True, blank=True)
    min_lap_time = models.DurationField()
    notes = models.CharField(max_length=1024, null=True, blank=True)
    logo = models.ImageField(upload_to='images/', null=True, blank=True)
    all_emails_sent = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def get_absolute_edit_url(self):
        return reverse("tracker:edit-race", kwargs={"pk": self.id})

    def runner_email_count(self):
        """Return count of distinct runner emails for this race (for bulk email)."""
        return self.runners_set.exclude(email__isnull=True).exclude(email='').values('email').distinct().count()

    def unpaid_runner_email_count(self):
        """Return count of unpaid runners with email (for payment reminder bulk email)."""
        return self.runners_set.filter(paid=False).exclude(email__isnull=True).exclude(email='').count()


class RfidTag(models.Model):
    """Reusable RFID tag: tag_number matches runner number when auto-assigned. Can be used for multiple runners over time."""
    name = models.CharField(max_length=255, blank=True, help_text="Optional label for this tag")
    tag_number = models.IntegerField(unique=True, help_text="Number used when auto-assigning (same as runner number)")
    rfid_hex = models.CharField(max_length=512, help_text="Hex string from the physical RFID tag")

    class Meta:
        ordering = ['tag_number']
        verbose_name = 'RFID tag'
        verbose_name_plural = 'RFID tags'

    def __str__(self):
        if self.name:
            return f"{self.name} (#{self.tag_number})"
        if self.rfid_hex and len(self.rfid_hex) > 16:
            return f"Tag {self.tag_number} ({self.rfid_hex[:16]}...)"
        return f"Tag {self.tag_number}"


class runners(models.Model):
    gender = (
        ('male', 'Male'),
        ('female', 'Female')
    )
    race_type = (
        ('running', 'Running'),
        ('walking', 'Walking')
    )
    shirt_size = (
        ('Kids XS', 'Kids XS'),
        ('Kids S', 'Kids S'),
        ('Kids M', 'Kids M'),
        ('Kids L', 'Kids L'),
        ('Extra Small', 'Extra Small'),
        ('Small', 'Small'),
        ('Medium', 'Medium'),
        ('Large', 'Large'),
        ('XL', 'XL'),
        ('XXL', 'XXL')
    )
    age_bracket = (
        ('0-12', '0-12'),
        ('12-17', '12-17'),
        ('18-34', '18-34'),
        ('35-49', '35-49'),
        ('50+', '50+')
    )

    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    email = models.EmailField(max_length=254)
    age = models.CharField(
        max_length=50, choices=age_bracket)
    gender = models.CharField(
        max_length=50, choices=gender)
    number = models.IntegerField(null=True, blank=True)
    tag = models.ForeignKey(
        RfidTag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='runner_assignments',
        help_text='Reusable RFID tag; auto-assigned by tag_number when assigning runner numbers',
    )
    race = models.ForeignKey(race, on_delete=models.PROTECT)
    race_completed = models.BooleanField(null=True, blank=True)
    total_race_time = models.DurationField(
        blank=True, null=True,
        help_text='Gun time: from race start to finish'
    )
    chip_time = models.DurationField(
        blank=True, null=True,
        help_text='Chip time: from first crossing (lap 0) or race start to finish'
    )
    race_avg_speed = models.DecimalField(
        max_digits=10, decimal_places=2, blank=True, null=True)
    race_avg_pace = models.DurationField(blank=True, null=True)
    place = models.IntegerField(blank=True, null=True)
    type = models.CharField(
        max_length=64, choices=race_type, null=True, blank=True)
    shirt_size = models.CharField(
        max_length=64, choices=shirt_size)
    notes = models.CharField(max_length=512, null=True, blank=True)
    email_sent = models.BooleanField(default=False)
    paid = models.BooleanField(default=False, help_text='True when PayPal donation/payment completed')
    created_at = models.DateTimeField(auto_now_add=True)
    signup_confirmation_sent = models.BooleanField(default=False)

    def __str__(self):
        return self.first_name + " " + self.last_name

    @property
    def rfid_tag_hex(self):
        return (self.tag.rfid_hex or '') if self.tag else ''


class laps(models.Model):
    runner = models.ForeignKey(runners, on_delete=models.CASCADE)
    time = models.DateTimeField(auto_now=False, auto_now_add=False)
    lap = models.IntegerField()
    attach_to_race = models.ForeignKey(race, on_delete=models.CASCADE)
    duration = models.DurationField()
    average_speed = models.DecimalField(max_digits=10, decimal_places=2)
    average_pace = models.DurationField()

    def __str__(self):
        return self.attach_to_race.name + "/" + str(self.runner.number)


class BannerQuerySet(models.QuerySet):
    _page_fields = {'home': 'show_on_home', 'signup': 'show_on_signup', 'results': 'show_on_results', 'countdown': 'show_on_countdown'}

    def active_for_page(self, page_slug):
        """Return banners that are active and shown on the given page (e.g. 'home', 'signup')."""
        field = self._page_fields.get(page_slug)
        if not field:
            return self.none()
        return self.filter(active=True, **{field: True})


class Banner(models.Model):
    """Editable banners shown on public pages. Use the checkboxes to choose which pages each banner appears on."""

    # Page slugs for filtering in views (use these with Banner.objects.active_for_page('home'))
    PAGE_HOME = 'home'
    PAGE_SIGNUP = 'signup'
    PAGE_RESULTS = 'results'
    PAGE_COUNTDOWN = 'countdown'

    title = models.CharField(max_length=200, blank=True)
    subtitle = models.CharField(max_length=1024, blank=True)
    background_color = models.CharField(max_length=30, default='#ffffff')
    image = models.ImageField(upload_to='banners/', blank=True)
    active = models.BooleanField(default=False)

    # Which public pages this banner appears on (check as many as you want)
    show_on_home = models.BooleanField(
        default=False,
        help_text='Show on the public home / race list page',
    )
    show_on_signup = models.BooleanField(
        default=False,
        help_text='Show on the sign-up page',
    )
    show_on_results = models.BooleanField(
        default=False,
        help_text='Show on results / completed race pages',
    )
    show_on_countdown = models.BooleanField(
        default=False,
        help_text='Show on countdown / upcoming race page',
    )

    def __str__(self):
        return self.title or '(no title)'

    objects = models.Manager.from_queryset(BannerQuerySet)()

    def pages_display(self):
        """Comma-separated list of page names for admin list display."""
        names = []
        if self.show_on_home:
            names.append('Home')
        if self.show_on_signup:
            names.append('Sign up')
        if self.show_on_results:
            names.append('Results')
        if self.show_on_countdown:
            names.append('Countdown')
        return ', '.join(names) if names else '—'


class ApiKey(models.Model):
    name = models.CharField(max_length=255)
    key = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - {self.key[:10]}..."


class SiteSettings(models.Model):
    """
    Singleton settings for the site (PayPal, etc.). Use get_settings() to get the one instance.
    """
    paypal_enabled = models.BooleanField(
        default=False,
        help_text='When on, signup redirects to PayPal with entry fee; when off, signup goes to success page only.'
    )
    signup_confirmation_timeout_minutes = models.PositiveIntegerField(
        default=15,
        help_text='Send signup confirmation to runners who have not received one and signed up more than this many minutes ago (or have already paid). The background worker (same as race emails) uses this value.'
    )
    site_base_url = models.URLField(
        blank=True,
        max_length=500,
        help_text='Base URL of this site (e.g. https://example.com). Used for pay-later links in signup confirmation emails.'
    )

    class Meta:
        verbose_name = 'Site settings'
        verbose_name_plural = 'Site settings'

    def __str__(self):
        return 'Site settings'

    @classmethod
    def get_settings(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={'paypal_enabled': False})
        return obj


class EmailSendJob(models.Model):
    """Queue entry for sending one bulk email to all runners of a race. Processed by background worker."""
    STATUS_QUEUED = 'queued'
    STATUS_SENDING = 'sending'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_SENDING, 'Sending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    ]
    race = models.ForeignKey(race, on_delete=models.CASCADE)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    unpaid_reminder = models.BooleanField(
        default=False,
        help_text='When True, send only to unpaid runners and append payment link to each email.',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_QUEUED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['created_at']
