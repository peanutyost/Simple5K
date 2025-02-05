from django import forms
from django.shortcuts import get_object_or_404
from .models import (laps,
                     runners,
                     race,
                     )
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
            'is_current',
            'status',
            'Entry_fee',
            'date',
            'distance',
            'laps_count',
        ]

        widgets = {
            'status': forms.Select(choices=race.status_choices),
            'name': forms.TextInput(attrs={'placeholder': 'Enter race name'}),
            'Entry_fee': forms.NumberInput(attrs={'placeholder': 'Enter entry fee'}),
        }

        labels = {
            'name': 'Race Name',
            'is_current': 'Is Current Race',
            'status': 'Status',
            'Entry_fee': 'Entry Fee',
            'date': 'Date',
            'distance': 'Distance',
            'laps_count': 'Laps Count',
        }

        help_texts = {
            'name': 'Enter the name of the race',
            'is_current': 'Check if this is the current race',
            'status': 'Select the status of the race',
            'Entry_fee': 'Enter the entry fee for the race',
            'date': 'Enter the date of the race',
            'distance': 'Enter the distance of the race in meters',
            'laps_count': 'Enter the number of laps in the race',
        }


class LapForm(forms.Form):
    runnernumber = forms.IntegerField(label="Runners Number", widget=forms.TextInput(attrs={'autofocus': 'autofocus'}))


class addRunnerForm(forms.Form, forms.ModelForm):

    class Meta:
        model = runners
        fields = [
            'first_name',
            'last_name',
            'number',
            'gender',
            'race',
            'type',
            'notes'
        ]


class raceStart(forms.Form):

    racename = forms.ModelChoiceField(queryset=race.objects.all())


class runnerStats(forms.Form):
    # Check if there is a current race, if so use that as the initial value for racename field.

    current_race = get_object_or_404(race, is_current=True) if race.objects.exists() else None

    racename = forms.ModelChoiceField(queryset=race.objects.all(), initial=current_race)

    runnernumber = forms.IntegerField(label="Runner Number")


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
