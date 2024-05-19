from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.db.models import F, Q
from django.http import Http404, HttpResponse
from datetime import datetime

from .models import race, runners, laps
from .forms import LapForm, addRunnerForm, raceStart

# Create your views here.
def laps_view(request):
    p = []
    if request.method == 'POST':
        data = request.POST
        runnerNumber = data['runnernumber']
        runner_attached = get_object_or_404(runners, number=runnerNumber)
        race_attached = get_object_or_404(race, is_current=True)
        alllaps = laps.objects.filter(attach_to_race=race_attached, runner=runner_attached)
        
        if not alllaps.exists():
            thislap = 1
            lapDuration = datetime.now().astimezone() - race_attached.start_time

        else:
            lapsrun = alllaps.order_by('-lap').first()
            thislap = lapsrun.lap + 1
            lapDuration = datetime.now().astimezone() - lapsrun.time
            if thislap == race_attached.laps_count:
                runner_attached.race_completed = True
                runner_attached.total_race_time = datetime.now().astimezone() - race_attached.start_time
                totalracetimesecond = runner_attached.total_race_time.total_seconds()
                kmhtotal = (race_attached.distance / 1000) / (totalracetimesecond / 3600)
                mphtotal = kmhtotal * 0.621371
                print(mphtotal)
                runner_attached.race_avg_speed = mphtotal
                runner_attached.save()
                

        kmran = (race_attached.distance/race_attached.laps_count)/1000
        laptimeseconds = lapDuration.total_seconds()
        laptimehours = laptimeseconds / 3600
        kmh = kmran / laptimehours
        mph = kmh * 0.621371
        
        timenow = datetime.now().astimezone()
        p = laps(attach_to_race=race_attached, runner=runner_attached,
                 lap=thislap, duration=lapDuration, average_speed=mph,
                 time=timenow)
        p.save()

    form = LapForm()
    if p:
        context = {
            "form": form,
            "data": p
        }
    else:
        context = {
            "form": form
        }

    return render(request, "tracker/laps.html", context=context)

def add_runner_view(request):
    
    form = addRunnerForm(request.POST or None)
    context = {"form": form}
    
    if request.method == "POST":
        if form.is_valid():
            lv = form.save()
        else:
            return render(request, "tracker/add_runner.html",
                          context={
                            "form": form
                          })
        
    form = addRunnerForm()
    form.fields['race'].initial = race.objects.get(is_current=True)
    context = {"form": form}
    return render(request, "tracker/add_runner.html", context=context)

def race_start_view(request):
    form = raceStart(request.POST or None)
    context = {"form": form}
        
    if request.method == "POST":
        if form.is_valid():
            race.objects.update(is_current=False)
            lv = race.objects.get(name=form.cleaned_data['racename'])
            now = datetime.now().astimezone()
            lv.start_time = now
            lv.is_current = True
            lv.save()
            return redirect("tracker:laps-record")
        else:
            return render(request, "tracker/race_start.html",
                          context={
                            "form": form
                          })
            
    return render(request, "tracker/race_start.html", context=context)