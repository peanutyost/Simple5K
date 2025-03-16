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
        max_length=50, choices=gender, blank=True, null=True)
    number = models.IntegerField(null=True, blank=True)
    rfid_tag = models.BinaryField(max_length=496, blank=True, null=True)
    race = models.ForeignKey(race, on_delete=models.PROTECT)
    race_completed = models.BooleanField(null=True, blank=True)
    total_race_time = models.DurationField(blank=True, null=True)
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

    def __str__(self):
        return self.first_name + " " + self.last_name

    @property
    def rfid_tag_hex(self):
        return self.rfid_tag.hex()


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


class Banner(models.Model):
    pages = (
        ('all', 'All Pages'),
        ('signup', 'Sign Up Page'),
        ('results', 'Results Page'),
        ('countdown', 'Countdown Page'),
    )

    title = models.CharField(max_length=200, blank=True)
    subtitle = models.CharField(max_length=1024, blank=True)
    background_color = models.CharField(max_length=30, default='#ffffff')
    image = models.ImageField(upload_to='banners/', blank=True)
    active = models.BooleanField(default=False)
    pages = models.CharField(max_length=20, choices=pages, default='all')

    def __str__(self):
        return self.title


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
