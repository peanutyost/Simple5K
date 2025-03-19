from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.db.models import F, Q, Window, IntegerField, OrderBy
from django.db.models.functions import Rank
from django.urls import reverse
from django.http import Http404, HttpResponse, JsonResponse, HttpResponseNotFound
from datetime import datetime, timedelta
from django.utils import timezone
from django.views.generic.edit import FormView, UpdateView
from django.views.generic.list import ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.views.decorators.cache import cache_page
from django.core.mail import EmailMessage, send_mail
from django.conf import settings
from functools import wraps
import json
import pytz

from .models import race, runners, laps, Banner, ApiKey
from .forms import LapForm, raceStart, runnerStats, SignupForm, RaceForm, RaceSelectionForm
from .pdf_gen import generate_race_report


def require_api_key(view_func):
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            return JsonResponse({'error': 'Invalid API key'}, status=401)

        try:
            ApiKey.objects.get(key=api_key, is_active=True)
        except ApiKey.DoesNotExist:
            return JsonResponse({'error': 'Invalid API key'}, status=401)

        return view_func(request, *args, **kwargs)
    return wrapped_view


def cache_unless_authenticated(timeout):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped_view(request, *args, **kwargs):
            if request.user.is_authenticated:
                # Bypass caching and return fresh response for authenticated users
                return view_func(request, *args, **kwargs)
            else:
                # Cache the response for anonymous users
                return cache_page(timeout)(view_func)(request, *args, **kwargs)
        return wrapped_view
    return decorator


def calculate_age_bracket_placement(runner, race_obj):
    """
    Calculates a runner's placement within their age bracket for a given race.

    Args:
        runner: A runners object representing the runner in question.
        race_obj: A race object for the race to calculate placement in.

    Returns:
        The runner's placement within their age bracket (an integer), or None
        if the runner's total_race_time is not available or if there are no
        other runners in the same age bracket for that race.
    """

    if runner.total_race_time is None:
        return None  # Cannot calculate placement without a total race time.

    # Get all runners in the race who are in the same age bracket
    same_age_bracket_runners = runners.objects.filter(
        race=race_obj,
        age=runner.age,
        total_race_time__isnull=False  # Excludes runners with NULL total_race_time
    ).annotate(
        rank=Window(
            expression=Rank(),
            partition_by=F('age'),
            order_by='total_race_time'
        )
    ).values('pk', 'rank')
    # Find the runner in the queryset of same_age_bracket_runners

    try:  # If that runners exist

        runner_rank = next((item['rank'] for item in same_age_bracket_runners if item['pk'] == runner.pk), None)
        return runner_rank
    except StopIteration:
        return None  # if no same bracket runner exist


def prepare_race_data(race_obj, runner_obj):
    """
    Prepares the race data for the PDF report, including runner details,
    lap information, and competitor placings.
    """
    race_info = {
        'name': race_obj.name,
        'date': race_obj.date.strftime('%Y-%m-%d'),
        'distance': race_obj.distance,
    }
    if race_info is None:
        return None

    # Runner Details
    runner_details = {
        'name': f"{runner_obj.first_name} {runner_obj.last_name}",
        'number': runner_obj.number if runner_obj.number else "N/A",
        'age_bracket': runner_obj.age if runner_obj.age else "N/A",
        'gender': runner_obj.gender if runner_obj.gender else "N/A",
        'type': runner_obj.type if runner_obj.type else "N/A",
        'shirt_size': runner_obj.shirt_size if runner_obj.shirt_size else "N/A",
        'total_time': str(runner_obj.total_race_time) if runner_obj.total_race_time else "N/A",
        'race_avg_speed': float(runner_obj.race_avg_speed)if runner_obj.race_avg_speed else "N/A",
        'place': runner_obj.place if runner_obj.place else "N/A",
        'avg_pace': str(timedelta(seconds=round(
            runner_obj.race_avg_pace.total_seconds()))) if runner_obj.race_avg_pace else "N/A",
        'age_group_placement': calculate_age_bracket_placement(
            runner_obj, race_obj) if calculate_age_bracket_placement(runner_obj, race_obj) else "N/A"
    }
    if runner_details is None:
        return None

    # Lap Data
    laps_data = []
    for lap in laps.objects.filter(runner=runner_obj).order_by('lap'):
        laps_data.append({
            'lap': lap.lap,
            'time': lap.time.strftime('%H:%M:%S'),
            'duration': str(lap.duration),
            'average_speed': float(lap.average_speed),
            'average_pace': str(timedelta(seconds=round(lap.average_pace.total_seconds()))),
        })

    # Competitor Placement Data (2 faster, 2 slower)
    # Find 2 runners faster
    if runner_obj.total_race_time == "N/A" or runner_obj.total_race_time is None:
        return None
    else:

        faster_runners = runners.objects.filter(
            race=race_obj,
            total_race_time__lt=runner_obj.total_race_time
        ).order_by('total_race_time')[:2]

        slower_runners = runners.objects.filter(
            race=race_obj,
            total_race_time__gt=runner_obj.total_race_time
        ).order_by('-total_race_time')[:2]

        def format_runner(runner):
            return [runner.first_name + ' ' + runner.last_name, f"{runner.total_race_time}"] if runner else "N/A"

        competitor_data = {
            'faster_runners': [format_runner(runner) for runner in faster_runners],
            'slower_runners': [format_runner(runner) for runner in slower_runners],
        }

    return {
        'race': race_info,
        'runner': runner_details,
        'laps': laps_data,
        'competitors': competitor_data,
    }


def send_race_report_email(runner_id, race_id):
    """
    Generates a race report, attaches it to an email, and sends the email
    to the runner.
    Args:
        runner_id: The ID of the runner.
        race_id: The ID of the race.
    Returns:
        None.  Raises exceptions if email sending fails.
    """
    race_obj = get_object_or_404(race, pk=race_id)
    runner_obj = get_object_or_404(runners, number=runner_id)
    # Generate the PDF
    pdf_filename = f"race_report_{race_obj.name}_{runner_obj.first_name}_{runner_obj.last_name}.pdf"
    race_data = prepare_race_data(race_obj, runner_obj)

    try:
        # Generate the race report PDF as bytes
        pdf_content = generate_race_report(pdf_filename, race_data, 'file')  # Returns the pdf content as bytes

        # Construct the email
        subject = "Your Race Report"
        body = f"{runner_obj.first_name} {runner_obj.last_name},\nPlease find attached your race report.\n\n{race_obj.name} Team"
        from_email = settings.EMAIL_HOST_USER  # Use the email address configured in settings.py
        recipient_list = [runner_obj.email]  # The runner's email address

        # Create an EmailMessage object for attachments.  Use EmailMessage not send_mail for more control
        email = EmailMessage(subject, body, from_email, recipient_list)

        # Attach the PDF directly from the bytes
        email.attach(pdf_filename, pdf_content, "application/pdf")  # Attach the report
        # If you're using Microsoft 365 and have configured TLS settings:
        # email.fail_silently = False  # Raise exceptions on email sending failures
        # Send the email
        try:
            email.send()  # Actually sends the email.

        except Exception as e:
            print(f"Error sending email: {e}")
            raise  # Re-raise to alert the caller

    except Exception as e:
        print(f"Error processing or sending race report for {runner_obj.email}: {e}")  # Log the combined error.
        # Potentially log details to database
        raise  # Re-raise the exception to  handle it further up


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


class GenerateRaceReportView(LoginRequiredMixin, View):
    def get(self, request, race_id, runner_id):
        race_obj = get_object_or_404(race, pk=race_id)
        runner_obj = get_object_or_404(runners, number=runner_id)

        # Prepare data for the report
        race_data = prepare_race_data(race_obj, runner_obj)
        # Generate the PDF
        if race_data is None:
            return HttpResponseNotFound("No runner or race data found")
        else:
            pdf_filename = f"race_report_{race_obj.name}_{runner_obj.first_name}_{runner_obj.last_name}.pdf"
        response = generate_race_report(pdf_filename, race_data, 'response')
        return response


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


def format_remaining_time(end_time):
    """Format remaining time into days, hours, minutes, seconds"""
    # Get current time in UTC
    now = timezone.now()

    # If end_time is naive (has no timezone info), localize it to UTC
    if timezone.is_naive(end_time):
        end_time = timezone.make_aware(end_time, timezone=timezone.get_default_timezone())

    # Ensure both times are in the same timezone before comparison
    now_utc = now.astimezone(timezone.get_default_timezone())
    end_time_utc = end_time.astimezone(timezone.get_default_timezone())

    if end_time_utc <= now_utc:
        return {'days': 0, 'hours': 0, 'minutes': 0, 'seconds': 0}

    delta = end_time_utc - now_utc

    days = delta.days
    seconds = delta.seconds
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    return {
        'days': days,
        'hours': hours,
        'minutes': minutes,
        'seconds': seconds
    }


@login_required
def mark_runner_finished(request):
    if request.method == 'POST':
        runner_number = request.POST.get('runner_number')
        try:
            runner = runners.objects.get(number=runner_number)
            runner.race_completed = True
            runner.save()
            return JsonResponse({'success': True, 'message': f'Runner {runner_number} marked as finished.'})
        except runners.DoesNotExist:
            return JsonResponse({'success': False, 'message': f'Runner with number {runner_number} not found.'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'An error occurred: {str(e)}'})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})


# ---------------------------API---------------------------------------------
@csrf_exempt
@require_api_key
def record_lap(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    try:
        laps_data = json.loads(request.body)

        if not laps_data or not isinstance(laps_data, list):
            return JsonResponse({'error': 'Laps data must be a list'}, status=400)

        results = []

        for lap_data in laps_data:
            runner_rfid_hex = lap_data.get('runner_rfid')  # This now correctly gets from individual lap
            race_id = lap_data.get('race_id')  # This gets the race id for this particular lap
            timestamp = lap_data.get('timestamp')

            if not runner_rfid_hex:
                results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "Runner RFID required"})
                continue

            if not race_id:
                results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "Race ID required"})
                continue

            if not timestamp:
                results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "Timestamp is required"})
                continue

            try:
                runner_rfid = bytes.fromhex(runner_rfid_hex)  # Convert to bytes
                # Parse the timestamp into a timezone-aware datetime object
                time_naive = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
                current_time = time_naive.replace(tzinfo=pytz.utc)
                runner_obj = runners.objects.get(rfid_tag=runner_rfid)  # Get runner object, crucial to keep here
                race_obj = race.objects.get(id=race_id)  # get race object

                if race_obj.min_lap_time is None:
                    race_obj.min_lap_time = timedelta(seconds=0)

                # Calculate lap duration and averages
                previous_lap = laps.objects.filter(
                    runner=runner_obj,
                    attach_to_race=race_obj
                ).order_by('-lap').first()

                if runner_obj.race_completed is not True:
                    if previous_lap:
                        if current_time - previous_lap.time > race_obj.min_lap_time:
                            duration = current_time - previous_lap.time
                            lap_number = previous_lap.lap + 1
                            if lap_number == race_obj.laps_count:
                                runner_obj.race_completed = True

                                if runner_obj.gender is None:
                                    runner_obj.gender = 'male'
                                allfinnisher = runners.objects.filter(
                                    race_completed=True, gender=runner_obj.gender)

                                if not allfinnisher.exists():
                                    runner_obj.place = 1
                                else:
                                    prevfinnisher = allfinnisher.order_by('-place').first()
                                    runner_obj.place = prevfinnisher.place + 1

                                runner_obj.total_race_time = current_time - race_obj.start_time
                                totalracetimesecond = runner_obj.total_race_time.total_seconds()
                                kmhtotal = (race_obj.distance / 1000) / (totalracetimesecond / 3600)
                                mphtotal = kmhtotal * 0.621371
                                runner_obj.race_avg_speed = mphtotal

                                avg_pace_seconds = ((runner_obj.total_race_time.total_seconds() / 60) / (
                                    race_obj.distance / 1609.34)) * 60
                                runner_obj.race_avg_pace = timedelta(seconds=avg_pace_seconds)
                                runner_obj.save()
                        elif current_time - previous_lap.time <= race_obj.min_lap_time:
                            results.append({"runner_rfid": runner_rfid_hex, "status": "success"})
                            continue  # Skip processing this lap as it's too soon

                    else:
                        if current_time - race_obj.start_time > race_obj.min_lap_time:
                            duration = current_time - race_obj.start_time
                            lap_number = 1
                        elif current_time - race_obj.start_time <= race_obj.min_lap_time:
                            results.append({"runner_rfid": runner_rfid_hex, "status": "success"})
                            continue  # Skip processing this lap as it's too soon

                    distance_per_lap = race_obj.distance / 1000 / race_obj.laps_count
                    speed = (distance_per_lap / duration.total_seconds()) * 3600 * 0.621371
                    pace_seconds = ((duration.total_seconds() / 60) / (distance_per_lap / 1.60934)) * 60
                    pace = timedelta(seconds=pace_seconds)

                    laps_obj = laps.objects.create(
                        runner=runner_obj,
                        attach_to_race=race_obj,
                        time=current_time,
                        lap=lap_number,
                        duration=duration,
                        average_speed=speed,
                        average_pace=pace
                    )
                    laps_obj.save()  # Save to database
                    results.append({"runner_rfid": runner_rfid_hex, "status": "success"})

                else:
                    results.append({"runner_rfid": runner_rfid_hex, "status": "success"})

            except runners.DoesNotExist:

                results.append({"runner_rfid": runner_rfid_hex, "status": "success"})

            except race.DoesNotExist:

                results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "Race not found"})

            except Exception as e:
                results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": str(e)})

        return JsonResponse({'results': results})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_api_key
def update_race_time(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        race_id = data.get('race_id')
        action = data.get('action')  # 'start' or 'stop'
        timestamp = data.get('timestamp')
        time_naive = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
        current_time = time_naive.replace(tzinfo=pytz.utc)
        race_obj = race.objects.get(id=race_id)

        if action == 'start':
            if race_obj.status not in ('in_progress', 'completed'):
                race_obj.start_time = current_time
                race_obj.status = 'in_progress'
                race_obj.save()
        elif action == 'stop':
            if race_obj != 'completed':
                race_obj.end_time = current_time
                race_obj.status = 'completed'
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)

        race_obj.save()

        return JsonResponse({
            'status': 'success'
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@csrf_exempt
@require_api_key
def update_rfid(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
        runner_number = data.get('runner_number')
        rfid_tag = data.get('rfid_tag')
        race_id = data.get('race_id')

        race_local = race.objects.get(id=race_id)
        runner_obj = runners.objects.filter(number=runner_number).filter(race=race_local).first()
        runner_obj.rfid_tag = bytes.fromhex(rfid_tag)
        runner_obj.save()

        return JsonResponse({
            'status': 'success',
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@require_api_key
def get_available_races(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        available_races = race.objects.exclude(
            status__in=['completed']
        ).values('id', 'name', 'status', 'date', 'scheduled_time')

        return JsonResponse({
            'status': 'success',
            'races': list(available_races)
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# View for generating API keys
@login_required
def generate_api_key(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        if name:
            api_key = ApiKey.objects.create(name=name)
            return render(request, 'tracker/generate_api_key.html', {'api_key': api_key})
    return render(request, 'tracker/generate_api_key.html')


# ----------------------------Assign numbers--------------------------------------
@login_required
def assign_numbers(request):
    if request.method == 'POST':
        race_id = request.POST.get('race')
        race_local = get_object_or_404(race, id=race_id)

        # Get all runners in the race without a number
        runners_without_number = runners.objects.filter(race=race_local, number__isnull=True).order_by('id')
        print(runners_without_number)
        print(race_local)
        if runners_without_number.exists():
            # Check if there are any numbers already assigned
            existing_numbers = runners.objects.filter(race=race_local, number__isnull=False).values_list('number', flat=True)

            if existing_numbers:
                next_number = max(existing_numbers) + 1
            else:
                next_number = race_local.number_start or 1  # Default to 1 if number_start is None

            for runner in runners_without_number:
                runner.number = next_number
                runner.save()
                next_number += 1
            messages.success(request, 'Numbers assigned successfully!')
            return redirect('tracker:assign_numbers')  # Redirect back with success message
        else:
            error_message = "All runners already have numbers assigned."
            return render(request, 'tracker/assign_numbers.html', {'error_message': error_message})

    races = race.objects.exclude(status='in_progress').exclude(status='completed')
    form = RaceSelectionForm()
    return render(request, 'tracker/assign_numbers.html', {'races': races, 'form': form})


# ---------------------------Public Views------------------------------------------


@cache_unless_authenticated(60)
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
                    'duration': timedelta(seconds=round(lap.duration.total_seconds())),
                    'average_speed': lap.average_speed
                })

            runner_times.append({
                'number': arunner.number,
                'name': f"{arunner.first_name} {arunner.last_name}",
                'total_race_time': timedelta(seconds=round(
                    arunner.total_race_time.total_seconds())) if not None else "Not Finished",
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


def race_signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            selected_race_id = form.cleaned_data['race'].id
            form.save()
            return redirect(reverse('tracker:signup-success', args=[selected_race_id]))  # You'll need to define this URL
    else:
        form = SignupForm()
    current_races = race.objects.filter(status='signup_open').order_by('date', 'scheduled_time')
    banners = Banner.objects.filter(active=True)
    context = {'form': form, 'current_races': current_races, 'banners': banners}
    return render(request, 'tracker/signup.html', context)


def signup_success(request, pk):
    try:
        raceobj = race.objects.get(id=pk)
        context = {'entry_fee': raceobj.Entry_fee,
                   'race_date': raceobj.date,
                   'race_time': raceobj.scheduled_time}
    except race.DoesNotExist:
        context = {'error': 'Race not found.'}

    return render(request, 'tracker/signup_success.html', context)


def race_countdown(request):
    """Get countdown for all upcoming races"""
    # Get races that haven't started yet (status is signup_open or signup_closed)
    upcoming_races = race.objects.filter(status__in=['signup_open', 'signup_closed']).order_by('date', 'scheduled_time')

    # Calculate remaining time for each race
    race_data = []
    for r in upcoming_races:
        # Combine date and scheduled_time into a datetime object
        start_time = datetime.combine(r.date, r.scheduled_time)

        # Get formatted remaining time
        remaining = format_remaining_time(start_time)

        race_data.append({
            'id': r.id,
            'name': r.name,
            'distance': f"{r.distance} meters",
            'laps_count': f"{r.laps_count} laps",
            'entry_fee': f"${r.Entry_fee:.2f}",
            'remaining': remaining
        })

    return JsonResponse(race_data, safe=False)


def race_list(request):
    banners = Banner.objects.filter(active=True)
    """Render the race list page"""
    return render(request, 'tracker/race_list.html', context={'banners': banners})
