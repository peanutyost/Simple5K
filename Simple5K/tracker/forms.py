from django import forms
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

    racename = forms.ModelChoiceField(queryset=race.objects.all(), initial=race.objects.get(is_current=True))
    runnernumber = forms.IntegerField(label="Runner Number")
