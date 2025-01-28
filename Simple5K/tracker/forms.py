from django import forms
from django.shortcuts import get_object_or_404
from .models import (laps,
                     runners,
                     race,
                     )

BOOL_CHECKLIST_OPTIONS = (
    (True, 'Yes'),
    (False, 'No'),
)


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
    # need to make this fail gracefully
    if get_object_or_404(race, is_current=True):

        racename = forms.ModelChoiceField(queryset=race.objects.all(), initial=race.objects.get(is_current=True))
    else:
        racename = forms.ModelChoiceField(queryset=race.objects.all(), initial=None)

    runnernumber = forms.IntegerField(label="Runner Number")

class SignupForm(forms.ModelForm):
    class Meta:
        model = runners
        fields = ['first_name', 'last_name', 'gender', 'race', 'type']
        # You can customize widgets and labels here if needed
        widgets = {
            'race': forms.Select(attrs={'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'type': forms.Select(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'first_name': 'First Name',
            'last_name': 'Last Name',
            'gender': 'Gender',
            'race': 'Select Race',
            'type': 'Participant Type',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter the race choices to only show current races
        self.fields['race'].queryset = race.objects.filter(is_current=True)
