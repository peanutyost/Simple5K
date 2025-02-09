from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.db.models import F, Q
from django.urls import reverse
from django.http import Http404, HttpResponse
from datetime import datetime
from django.views.generic.edit import FormView, UpdateView
from django.views.generic.list import ListView
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import race, runners, laps
from .forms import LapForm, raceStart, runnerStats, SignupForm, RaceForm
from .pdf_gen import generate_race_report


class RaceAdd(LoginRequiredMixin, FormView):
    form_class = RaceForm
    template_name = 'tracker/race_add.html'
    success_url = '/'

    def form_valid(self, form):
        # This method is called when the form is valid.
        form.save()
        return super().form_valid(form)


class RaceEdit(LoginRequiredMixin, UpdateView):
    model = race
    form_class = RaceForm
    template_name = 'tracker/race_add.html'
    success_url = '/'


class ListRaces(LoginRequiredMixin, ListView):
    model = race
    queryset = race.objects.all()
    template_name = 'tracker/list_races.html'
    context_object_name = 'object_list'
    paginate_by = 50
    ordering = ['-date']


@login_required
def laps_view(request):
    p = []
    if request.method == 'POST':
        data = request.POST
        runnerNumber = data['runnernumber']
        runner_attached = get_object_or_404(runners, number=runnerNumber)
        race_attached = race.objects.filter(status='in_progress').first()
        alllaps = laps.objects.filter(
            attach_to_race=race_attached, runner=runner_attached)

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

                allfinnisher = runners.objects.filter(
                    race_completed=True, gender=runner_attached.gender)
                if not allfinnisher.exists():
                    runner_attached.place = 1
                else:
                    prevfinnisher = allfinnisher.order_by('-place').first()
                    runner_attached.place = prevfinnisher.place + 1
                runner_attached.race_completed = True
                runner_attached.total_race_time = datetime.now().astimezone() - race_attached.start_time
                totalracetimesecond = runner_attached.total_race_time.total_seconds()
                kmhtotal = (race_attached.distance / 1000) / (totalracetimesecond / 3600)
                mphtotal = kmhtotal * 0.621371
                runner_attached.race_avg_speed = mphtotal

                runner_attached.save()

        kmran = (race_attached.distance / race_attached.laps_count) / 1000
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
def race_start_view(request):
    form = raceStart(request.POST or None)
    context = {"form": form}

    if request.method == "POST":
        if form.is_valid():
            # need to loop thru and clear all other races to not current.
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
    current_race = race.objects.filter(status='in_progress').first()

    # Initialize an empty list to store runner times
    runner_times = []

    if current_race:
        # Get all runners for the current race
        runnersall = runners.objects.filter(race=current_race).order_by(F('place').asc(nulls_last=True))

        # Create a list of runner names and their total race times
        for arunner in runnersall:
            run_laps = []
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
            raceobj = race.objects.filter(status='in_progress').first()
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
            runnersobj['number'] = runnerobj.number
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


@login_required
def race_signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            selected_race_id = form.cleaned_data['race'].id
            form.save()
            return redirect(reverse('tracker:signup-success', args=[selected_race_id]))  # You'll need to define this URL
    else:
        form = SignupForm()
    current_races = race.objects.filter(status='signup_open')
    context = {'form': form, 'current_races': current_races}
    return render(request, 'tracker/signup.html', context)


@login_required
def signup_success(request, pk):
    try:
        raceobj = race.objects.get(id=pk)
        context = {'entry_fee': raceobj.Entry_fee,
                   'race_date': raceobj.date,
                   'race_time': raceobj.scheduled_time}
    except race.DoesNotExist:
        context = {'error': 'Race not found.'}

    return render(request, 'tracker/signup_success.html', context)


@login_required
def select_race(request):
    # Get all races where status is either 'signup_open' or 'signup_closed'
    races = race.objects.filter(
        Q(status='signup_open') | Q(status='signup_closed')
    )

    if request.method == 'POST':
        # Extract the selected race ID from POST data
        selected_race_id = request.POST.get('race', None)
        if selected_race_id:
            try:
                # Validate that the selected_race_id is a valid integer and exists in the database
                selected_race = race.objects.get(name=selected_race_id)

                # Redirect to 'view_shirts' URL with the selected_race_id as a parameter
                return redirect(reverse('tracker:view_shirts', kwargs={'pk': selected_race.pk}))
            except (ValueError, race.DoesNotExist):
                pass
    return render(request, 'tracker/select_race.html', {'races': races})


@login_required
def view_shirt_sizes(request, pk):
    # Get all runners for the selected race
    runners_in_race = runners.objects.filter(race=pk)

    # Calculate total number of runners
    total_runners = runners_in_race.count()

    # Get shirt size counts
    shirt_size_counts = {
        'Kids XS': 0,
        'Kids S': 0,
        'Kids M': 0,
        'Kids L': 0,
        'Extra Small': 0,
        'Small': 0,
        'Medium': 0,
        'Large': 0,
        'XL': 0,
        'XXL': 0
    }

    for runner in runners_in_race:
        if runner.shirt_size in shirt_size_counts:
            shirt_size_counts[runner.shirt_size] += 1

    return render(request, 'tracker/view_shirts.html', {
        'shirt_size_counts': shirt_size_counts,
        'total_runners': total_runners
    })


@login_required
def select_race_for_runners(request):
    # Get all races where status is either 'signup_open' or 'signup_closed'
    races = race.objects.filter(
        Q(status='signup_open') | Q(status='signup_closed')
    )

    if request.method == 'POST':
        # Extract the selected race ID from POST data
        selected_race_id = request.POST.get('race', None)
        if selected_race_id:
            try:
                # Validate that the selected_race_id is a valid integer and exists in the database
                selected_race = race.objects.get(name=selected_race_id)

                # Redirect to 'view_shirts' URL with the selected_race_id as a parameter
                return redirect(reverse('tracker:view_runners', kwargs={'pk': selected_race.pk}))
            except (ValueError, race.DoesNotExist):
                pass
    return render(request, 'tracker/select_race.html', {'races': races})


@login_required
def show_runners(request, pk):
    selected_race = get_object_or_404(race, pk=pk)
    race_runners = runners.objects.filter(race_id=pk)
    return render(request, 'tracker/view_runners.html', {'race': selected_race, 'runners': race_runners})
