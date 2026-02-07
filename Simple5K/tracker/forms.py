from django import forms
from .models import runners, race, SiteSettings
from captcha.fields import CaptchaField

BOOL_CHECKLIST_OPTIONS = (
    (True, 'Yes'),
    (False, 'No'),
)


class RaceForm(forms.ModelForm):
    class Meta:
        model = race
        fields = [
            'name',
            'status',
            'Entry_fee',
            'date',
            'scheduled_time',
            'number_start',
            'max_runners',
            'distance',
            'laps_count',
            'notes',
            'min_lap_time',
            'logo'
        ]

        widgets = {
            'status': forms.Select(choices=race.status_choices),
            'name': forms.TextInput(attrs={'placeholder': 'Enter race name'}),
            'Entry_fee': forms.NumberInput(attrs={'placeholder': 'Enter entry fee'}),
        }

        labels = {
            'name': 'Race Name',
            'status': 'Status',
            'Entry_fee': 'Entry Fee',
            'scheduled_time': 'Scheduled Time',
            'date': 'Date',
            'number_start': 'Starting Number',
            'max_runners': 'Max Runners',
            'distance': 'Distance',
            'laps_count': 'Laps Count',
            'notes': 'Notes',
            'min_lap_time': 'Minimum Lap Time',
            'logo': 'Logo'
        }

        help_texts = {
            'name': 'Enter the name of the race',
            'status': 'Select the status of the race',
            'Entry_fee': 'Enter the entry fee for the race',
            'date': 'Enter the date of the race',
            'distance': 'Enter the distance of the race in meters',
            'laps_count': 'Enter the number of laps in the race',
            'scheduled_time': 'Enter the scheduled starting time in 24H format',
            'number_start': 'Enter the starting number for the runner numbers',
            'max_runners': 'Enter the max number of participants for the race.',
            'notes': 'Enter notes to display on signup page.',
            'min_lap_time': 'Enter the minimum lap time in seconds.',
            'logo': 'Upload a logo for the race'
        }


class LapForm(forms.Form):
    runnernumber = forms.IntegerField(label="Runners Number", widget=forms.TextInput(attrs={'autofocus': 'autofocus'}))


class raceStart(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['racename'] = forms.ModelChoiceField(queryset=race.objects.all())


class runnerStats(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Move the database query here
        current_race = race.objects.filter(status='in_progress').first() if race.objects.exists() else None
        self.fields['racename'] = forms.ModelChoiceField(
            queryset=race.objects.all(),
            initial=current_race
        )
        self.fields['runnernumber'] = forms.IntegerField(label="Runner Number")


class SignupForm(forms.ModelForm):
    captcha = CaptchaField()

    class Meta:
        model = runners
        fields = ['first_name', 'last_name', 'email', 'age', 'gender', 'race', 'type', 'shirt_size', 'notes']
        # You can customize widgets and labels here if needed
        widgets = {
            'race': forms.Select(attrs={'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'type': forms.Select(attrs={'class': 'form-control'}),
            'age': forms.Select(attrs={'class': 'form-control'}),
            'shirt_size': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'May not be read by the race administators!'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),

        }
        labels = {
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'email': 'Email Address',
            'notes': 'Notes',
            'shirt_size': 'Shirt Size',
            'age': 'Age Bracket',
            'gender': 'Gender',
            'race': 'Select Race',
            'type': 'Participant Type',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter the race choices to only show current races
        self.fields['race'].queryset = race.objects.filter(status='signup_open')


class SiteSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = [
            'paypal_enabled',
            'signup_confirmation_timeout_minutes', 'site_base_url',
        ]
        widgets = {
            'paypal_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'signup_confirmation_timeout_minutes': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'site_base_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://example.com'}),
        }
        labels = {
            'paypal_enabled': 'Enable PayPal donation at signup',
            'signup_confirmation_timeout_minutes': 'Send signup email if runner is older than (minutes)',
            'site_base_url': 'Site base URL (for pay-later links in emails)',
        }


class RaceSelectionForm(forms.Form):
    race = forms.ModelChoiceField(queryset=race.objects.none(), label="Select Race")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['race'].queryset = race.objects.exclude(
            status__in=['in_progress', 'completed']
        ).order_by('date', 'name')


class RunnerInfoSelectionForm(forms.Form):
    SORT_CHOICES = (
        ('id', 'Runner ID'),
        ('last_name', 'Last Name'),
        ('first_name', 'First Name'),
        ('number', 'Runner Number'),
        ('paid', 'Payment Status'),
    )

    race = forms.ModelChoiceField(
        queryset=race.objects.order_by('name'),
        empty_label="-- Select a Race --",
        label="Select Race",
        widget=forms.Select(attrs={'class': 'form-control'})  # Optional styling
    )
    sort_by = forms.ChoiceField(
        choices=SORT_CHOICES,
        initial='last_name',
        label="Sort Runners By",
        widget=forms.Select(attrs={'class': 'form-control'})  # Optional styling
    )


class RaceSummaryForm(forms.Form):
    """Form to select a race for the race summary PDF (finishers by gender, lap stats, placements)."""
    race = forms.ModelChoiceField(
        queryset=race.objects.order_by('name'),
        empty_label="-- Select a Race --",
        label="Select Race",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
