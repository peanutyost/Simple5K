from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.db.models import F, Q
from django.http import Http404, HttpResponse
from datetime import datetime

from .models import race, runners, laps
from .forms import LapForm, addRunnerForm, raceStart, runnerStats
from .pdf_gen import generate_race_report


@login_required
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
                if runner_attached.gender is None:
                    runner_attached.gender = 'male'

                allfinnisher = runners.objects.filter(race_completed=True, gender=runner_attached.gender)
                if not allfinnisher.exists():
                    runner_attached.place = 1
                else:
                    prevfinnisher = allfinnisher.order_by('-place').first()
                    runner_attached.place = prevfinnisher.place + 1
                runner_attached.race_completed = True
                runner_attached.total_race_time = datetime.now().astimezone()-race_attached.start_time
                totalracetimesecond = runner_attached.total_race_time.total_seconds()
                kmhtotal = (race_attached.distance / 1000) / (totalracetimesecond / 3600)
                mphtotal = kmhtotal * 0.621371
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


@login_required
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


@login_required
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


def race_overview(request):
    current_race = race.objects.filter(is_current=True).first()

    # Initialize an empty list to store runner times
    runner_times = []

    if current_race:
        # Get all runners for the current race
        runnersall = runners.objects.filter(race=current_race).order_by(F('place').asc(nulls_last=True))

        # Create a list of runner names and their total race times
        for arunner in runnersall:
            run_laps =[]
            alap = laps.objects.filter(runner=arunner).order_by('lap')
            for lap in alap:
                run_laps.append({
                    'lap': lap.lap,
                    'duration': lap.duration,
                    'average_speed': lap.average_speed
                })  

            runner_times.append({
                'number': arunner.number,
                'name': f"{arunner.first_name} {arunner.last_name}",
                'total_race_time': arunner.total_race_time if not None else "Not Finished",
                'average_speed': arunner.race_avg_speed if not None else "Not Finished",
                'place': arunner.place,
                'laps': run_laps

            })

    # Pass the runner times to the template
    context = {
        'runner_times': runner_times,
        'race_name': current_race.name if current_race else "No current race"
    }

    return render(request, 'tracker/race_overview.html', context)


@login_required
def runner_stats(request):
    form = runnerStats(request.POST or None)
    context = {'form': form}
    if request.method == "POST":
        racetotalobj = {}
        lapsdict = {}
        runnersobj = {}
        if form.is_valid():
            raceobj = race.objects.get(is_current=True)
            runnerobj = runners.objects.get(number=form.cleaned_data['runnernumber'], race=form.cleaned_data['racename'])
            runnerlaps = laps.objects.filter(runner=runnerobj).order_by('lap')

            for lap in runnerlaps:
                lapdict = {}
                lapdict['runner'] = lap.runner.number
                lapdict['time'] = lap.time
                lapdict['lap'] = lap.lap
                lapdict['race'] = lap.attach_to_race.name
                lapdict['duration'] = lap.duration
                lapdict['average_speed'] = lap.average_speed
                lapsdict[int(lap.lap)] = lapdict

            racetotalobj['name'] = raceobj.name
            runnersobj['name'] = runnerobj.first_name + ' ' + runnerobj.last_name
            runnersobj['number'] =  runnerobj.number
            runnersobj['race'] = runnerobj.race.name
            runnersobj['race_completed'] = runnerobj.race_completed
            runnersobj['total_time'] = runnerobj.total_race_time
            runnersobj['place'] = runnerobj.place
            runnersobj['race_avg_speed'] = runnerobj.race_avg_speed
            runnersobj['laps'] = lapsdict
            racetotalobj['runners'] = runnersobj
        else:
            return render(request, 'tracker/runner_stats.html', context=context)
        response = generate_race_report("test.pdf", racetotalobj)
        return response

    return render(request, 'tracker/runner_stats.html', context=context)