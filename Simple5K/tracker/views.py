from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.db import IntegrityError
from django.db.models import F, Max, Q, Window, IntegerField, OrderBy, Value
from django.db.models.functions import Rank, Lower, Coalesce
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
import hmac
import hashlib
import io
import json
import logging
import pytz
import urllib.parse

logger = logging.getLogger(__name__)

from .models import race, runners, laps, Banner, ApiKey, RfidTag, SiteSettings, EmailSendJob
from .forms import LapForm, raceStart, runnerStats, SignupForm, RaceForm, RaceSelectionForm, RunnerInfoSelectionForm, RaceSummaryForm, SiteSettingsForm
from .pdf_gen import generate_race_report, create_runner_pdf, generate_race_summary_pdf
from .utils import safe_content_disposition_filename


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


def require_api_key_or_login(view_func):
    """Allow either valid X-API-Key header or authenticated session."""
    @wraps(view_func)
    def wrapped_view(request, *args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key:
            try:
                ApiKey.objects.get(key=api_key, is_active=True)
                return view_func(request, *args, **kwargs)
            except ApiKey.DoesNotExist:
                pass
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        return JsonResponse({'error': 'Invalid API key'}, status=401)
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


def _build_race_summary_data(race_obj):
    """Build summary data for race summary PDF: finishers by gender with lap stats and placements."""
    finishers = runners.objects.filter(
        race=race_obj,
        total_race_time__isnull=False
    ).order_by(F('place').asc(nulls_last=True))
    females = []
    males = []
    for runner in finishers:
        runner_laps = list(laps.objects.filter(runner=runner).order_by('lap'))
        if runner_laps:
            fastest = min(runner_laps, key=lambda l: l.duration)
            slowest = max(runner_laps, key=lambda l: l.duration)
            fastest_lap_time = fastest.duration
            fastest_lap_num = fastest.lap
            slowest_lap_time = slowest.duration
            slowest_lap_num = slowest.lap
        else:
            fastest_lap_time = fastest_lap_num = slowest_lap_time = slowest_lap_num = None
        row = {
            'name': f"{runner.first_name} {runner.last_name}".strip(),
            'number': runner.number,
            'fastest_lap_time': fastest_lap_time,
            'fastest_lap_num': fastest_lap_num,
            'slowest_lap_time': slowest_lap_time,
            'slowest_lap_num': slowest_lap_num,
            'overall_time': runner.total_race_time,
            'overall_place': runner.place,
            'age_group': runner.get_age_display() if runner.age else None,
            'age_group_place': calculate_age_bracket_placement(runner, race_obj),
        }
        if runner.gender == 'female':
            females.append(row)
        elif runner.gender == 'male':
            males.append(row)
    return {
        'race_name': race_obj.name,
        'females': females,
        'males': males,
    }


def prepare_race_data(race_obj, runner_obj):
    """
    Prepares the race data for the PDF report, including runner details,
    lap information, and competitor placings.
    """
    race_info = {
        'name': race_obj.name,
        'date': race_obj.date.strftime('%Y-%m-%d'),
        'distance': race_obj.distance,
        'logo': race_obj.logo.path if race_obj.logo else '',
    }

    # Runner Details
    runner_details = {
        'name': f"{runner_obj.first_name.capitalize()} {runner_obj.last_name.capitalize()}",
        'number': runner_obj.number if runner_obj.number else "N/A",
        'age_bracket': runner_obj.age if runner_obj.age else "N/A",
        'gender': runner_obj.gender.capitalize() if runner_obj.gender else "N/A",
        'type': runner_obj.type.capitalize() if runner_obj.type else "N/A",
        'shirt_size': runner_obj.shirt_size.capitalize() if runner_obj.shirt_size else "N/A",
        'total_time': str(timedelta(seconds=round(
            runner_obj.total_race_time.total_seconds()))) if runner_obj.total_race_time else "N/A",
        'gun_time': str(timedelta(seconds=round(
            runner_obj.total_race_time.total_seconds()))) if runner_obj.total_race_time else "N/A",
        'chip_time': str(timedelta(seconds=round(
            runner_obj.chip_time.total_seconds()))) if getattr(runner_obj, 'chip_time', None) else "N/A",
        'race_avg_speed': float(runner_obj.race_avg_speed)if runner_obj.race_avg_speed else "N/A",
        'place': runner_obj.place if runner_obj.place else "N/A",
        'avg_pace': str(timedelta(seconds=round(
            runner_obj.race_avg_pace.total_seconds()))) if runner_obj.race_avg_pace else "N/A",
        'age_group_placement': calculate_age_bracket_placement(
            runner_obj, race_obj) if calculate_age_bracket_placement(runner_obj, race_obj) else "N/A",
        'age_group_total': runners.objects.filter(
            race=race_obj, age=runner_obj.age, total_race_time__isnull=False
        ).count() if runner_obj.age else None,
    }

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

    # Competitor Placement Data (2 faster, 2 slower) — same gender only
    if runner_obj.total_race_time == "N/A" or runner_obj.total_race_time is None:
        competitor_data = {
            'faster_runners': None,
            'slower_runners': None,
        }
    else:
        base_filter = {'race': race_obj}
        if runner_obj.gender:
            base_filter['gender'] = runner_obj.gender
        faster_runners = runners.objects.filter(
            **base_filter,
            total_race_time__lt=runner_obj.total_race_time
        ).order_by('total_race_time')[:2]

        slower_runners = runners.objects.filter(
            **base_filter,
            total_race_time__gt=runner_obj.total_race_time
        ).order_by('-total_race_time')[:2]

        def format_runner(runner):
            return [runner.first_name + ' ' + runner.last_name, f"{str(timedelta(seconds=round(runner.total_race_time.total_seconds())))}"] if runner else "N/A"

        competitor_data = {
            'faster_runners': [format_runner(runner) for runner in faster_runners],
            'slower_runners': [format_runner(runner) for runner in slower_runners],
        }

    # Total finishers (for overall placement on PDF)
    total_finishers = runners.objects.filter(race=race_obj).exclude(place__isnull=True).count()

    # Gender placement: place among same gender only
    gender_place = None
    gender_total = None
    if runner_obj.gender and runner_obj.place is not None and runner_obj.total_race_time is not None:
        same_gender = runners.objects.filter(
            race=race_obj, gender=runner_obj.gender
        ).exclude(place__isnull=True).exclude(total_race_time__isnull=True)
        gender_total = same_gender.count()
        faster_same_gender = same_gender.filter(
            total_race_time__lt=runner_obj.total_race_time
        ).count()
        gender_place = faster_same_gender + 1

    runner_details['gender_place'] = gender_place
    runner_details['gender_total'] = gender_total

    return {
        'race': race_info,
        'runner': runner_details,
        'laps': laps_data,
        'competitors': competitor_data,
        'total_finishers': total_finishers,
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
    runner_obj = get_object_or_404(runners, pk=runner_id)
    # Generate the PDF
    pdf_filename = f"race_report_{race_obj.name}_{runner_obj.first_name}_{runner_obj.last_name}.pdf"
    race_data = prepare_race_data(race_obj, runner_obj)

    try:
        # Generate the race report PDF as bytes
        pdf_content = generate_race_report(pdf_filename, race_data, 'file')  # Returns the pdf content as bytes

        # Construct the email
        subject = "Your Race Report"
        body = f"{runner_obj.first_name} {runner_obj.last_name},\nPlease find your race report attached.\n\n{race_obj.name} Team"
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
        runner_obj = get_object_or_404(runners, race=race_obj, number=runner_id)

        # Prepare data for the report
        race_data = prepare_race_data(race_obj, runner_obj)
        # Generate the PDF
        if race_data is None:
            return HttpResponseNotFound("No runner or race data found")
        safe_name = safe_content_disposition_filename(f"{race_obj.name}_{runner_obj.first_name}_{runner_obj.last_name}")
        pdf_filename = f"race_report_{safe_name}.pdf"
        response = generate_race_report(pdf_filename, race_data, 'response')
        return response


@login_required
def race_start_view(request):
    form = raceStart(request.POST or None)
    context = {"form": form}

    if request.method == "POST":
        if form.is_valid():
            lv = race.objects.get(name=form.cleaned_data['racename'])
            now = timezone.now()
            lv.start_time = now
            lv.status = 'in_progress'
            lv.save()
            return redirect("tracker:race-overview")
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
        if form.is_valid():
            raceobj = race.objects.get(name=form.cleaned_data['racename'])
            runnerobj = runners.objects.get(number=form.cleaned_data['runnernumber'], race=form.cleaned_data['racename'])
            racetotalobj = prepare_race_data(raceobj, runnerobj)
        else:
            return render(request, 'tracker/runner_stats.html', context=context)
        filename = f"race_report_{raceobj.name}_{runnerobj.first_name}_{runnerobj.last_name}.pdf"
        response = generate_race_report(filename, racetotalobj, "response")
        return response

    return render(request, 'tracker/runner_stats.html', context=context)


@login_required
def select_race(request):
    # Get all races where status is either 'signup_open' or 'signup_closed'
    races = race.objects.filter(
        Q(status='signup_open') | Q(status='signup_closed')
    ).order_by('date', 'name')

    if request.method == 'POST':
        selected_race_name = request.POST.get('race', None)
        if selected_race_name:
            try:
                selected_race = race.objects.get(name=selected_race_name)
                return redirect(reverse('tracker:view_shirts', kwargs={'pk': selected_race.pk}))
            except (ValueError, race.DoesNotExist):
                pass
    return render(request, 'tracker/select_race.html', {
        'races': races,
        'page_title': 'View Shirt Sizes',
        'submit_label': 'View Shirt Sizes',
    })


@login_required
def view_shirt_sizes(request, pk):
    from django.db.models import Count
    race_obj = get_object_or_404(race, pk=pk)
    size_rows = runners.objects.filter(race=race_obj).values('shirt_size').annotate(count=Count('id'))
    size_counts = {row['shirt_size']: row['count'] for row in size_rows}
    all_sizes = ['Kids XS', 'Kids S', 'Kids M', 'Kids L', 'Extra Small', 'Small', 'Medium', 'Large', 'XL', 'XXL']
    shirt_size_counts = {s: size_counts.get(s, 0) for s in all_sizes}
    total_runners = sum(shirt_size_counts.values())

    return render(request, 'tracker/view_shirts.html', {
        'shirt_size_counts': shirt_size_counts,
        'total_runners': total_runners
    })


@login_required
def select_race_for_runners(request):
    races = race.objects.filter(
        Q(status='signup_open') | Q(status='signup_closed') | Q(status='in_progress') | Q(status='completed')
    ).order_by('date', 'name')

    if request.method == 'POST':
        selected_race_name = request.POST.get('race', None)
        if selected_race_name:
            try:
                selected_race = race.objects.get(name=selected_race_name)
                return redirect(reverse('tracker:view_runners', kwargs={'pk': selected_race.pk}))
            except (ValueError, race.DoesNotExist):
                pass
    return render(request, 'tracker/select_race.html', {
        'races': races,
        'page_title': 'View Runners',
        'submit_label': 'View Runners',
    })


@login_required
def show_runners(request, pk):
    selected_race = get_object_or_404(race, pk=pk)
    race_runners = runners.objects.filter(race_id=pk)
    # Use field.choices for attributes that are shadowed by model fields (gender, shirt_size)
    context = {
        'race': selected_race,
        'runners': race_runners,
        'age_brackets': runners.age_bracket,
        'genders': runners._meta.get_field('gender').choices,
        'race_types': runners.race_type,
        'shirt_sizes': runners._meta.get_field('shirt_size').choices,
    }
    return render(request, 'tracker/view_runners.html', context)


@csrf_exempt
@require_api_key_or_login
def add_runner(request):
    """POST: create a new runner for the given race. Expects race_id and runner fields. Returns JSON. Auth: API key or session."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'errors': ['Method not allowed']}, status=405)
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = request.POST.dict()
    race_id = data.get('race_id')
    if not race_id:
        return JsonResponse({'success': False, 'errors': ['race_id required']}, status=400)
    race_obj = get_object_or_404(race, pk=race_id)
    errors = []
    first_name = (data.get('first_name') or '').strip()
    last_name = (data.get('last_name') or '').strip()
    email = (data.get('email') or '').strip()
    age = (data.get('age') or '').strip()
    gender = (data.get('gender') or '').strip() or None
    auto_assign_number = data.get('auto_assign_number') in (True, 'true', 'True', 1, '1')
    number = data.get('number')
    if auto_assign_number:
        # Assign next available number for this race (same logic as assign_numbers)
        existing_numbers = runners.objects.filter(race=race_obj, number__isnull=False).values_list('number', flat=True)
        number = (max(existing_numbers) + 1) if existing_numbers else (race_obj.number_start or 1)
    elif number is not None and number != '':
        try:
            number = int(number)
            if number < 0:
                errors.append('Number must be non-negative')
        except (TypeError, ValueError):
            errors.append('Number must be an integer')
    else:
        number = None
    runner_type = (data.get('type') or '').strip() or None
    shirt_size = (data.get('shirt_size') or '').strip()
    notes = (data.get('notes') or '').strip() or None

    if not first_name:
        errors.append('First name is required')
    elif len(first_name) > 50:
        errors.append('First name too long')
    if not last_name:
        errors.append('Last name is required')
    elif len(last_name) > 50:
        errors.append('Last name too long')
    if not email:
        errors.append('Email is required')
    elif len(email) > 254:
        errors.append('Email too long')
    if not age or age not in [c[0] for c in runners.age_bracket]:
        errors.append('Valid age bracket is required')
    if not gender:
        errors.append('Gender is required')
    elif gender not in [c[0] for c in runners._meta.get_field('gender').choices]:
        errors.append('Invalid gender')
    if runner_type is not None and runner_type not in [c[0] for c in runners.race_type]:
        errors.append('Invalid type')
    if not shirt_size or shirt_size not in [c[0] for c in runners._meta.get_field('shirt_size').choices]:
        errors.append('Valid shirt size is required')

    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)
    runner_obj = runners.objects.create(
        race=race_obj,
        first_name=first_name,
        last_name=last_name,
        email=email,
        age=age,
        gender=gender,
        number=number,
        type=runner_type,
        shirt_size=shirt_size,
        notes=notes,
    )
    return JsonResponse({
        'success': True,
        'runner': {
            'id': runner_obj.id,
            'first_name': runner_obj.first_name,
            'last_name': runner_obj.last_name,
            'email': runner_obj.email,
            'age': runner_obj.age,
            'gender': runner_obj.gender or '',
            'number': runner_obj.number,
            'type': runner_obj.type or '',
            'shirt_size': runner_obj.shirt_size,
            'paid': runner_obj.paid,
        }
    })


@csrf_exempt
@require_api_key_or_login
def edit_runner(request):
    """POST: update runner fields. Expects runner_id and editable fields. Returns JSON. Auth: API key or session."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'errors': ['Method not allowed']}, status=405)
    try:
        data = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        data = request.POST.dict()
    runner_id = data.get('runner_id')
    if not runner_id:
        return JsonResponse({'success': False, 'errors': ['runner_id required']}, status=400)
    runner_obj = get_object_or_404(runners, pk=runner_id)
    errors = []
    if 'first_name' in data:
        v = (data.get('first_name') or '').strip()
        if not v:
            errors.append('First name is required')
        elif len(v) > 50:
            errors.append('First name too long')
        else:
            runner_obj.first_name = v
    if 'last_name' in data:
        v = (data.get('last_name') or '').strip()
        if not v:
            errors.append('Last name is required')
        elif len(v) > 50:
            errors.append('Last name too long')
        else:
            runner_obj.last_name = v
    if 'email' in data:
        v = (data.get('email') or '').strip()
        if not v:
            errors.append('Email is required')
        elif len(v) > 254:
            errors.append('Email too long')
        else:
            runner_obj.email = v
    if 'age' in data:
        v = (data.get('age') or '').strip()
        valid_ages = [c[0] for c in runners.age_bracket]
        if v not in valid_ages:
            errors.append('Invalid age bracket')
        else:
            runner_obj.age = v
    if 'gender' in data:
        v = (data.get('gender') or '').strip() or None
        if not v:
            errors.append('Gender is required')
        elif v not in [c[0] for c in runners._meta.get_field('gender').choices]:
            errors.append('Invalid gender')
        else:
            runner_obj.gender = v
    if 'number' in data:
        v = data.get('number')
        if v is None or v == '':
            runner_obj.number = None
        else:
            try:
                n = int(v)
                if n < 0:
                    errors.append('Number must be non-negative')
                else:
                    runner_obj.number = n
            except (TypeError, ValueError):
                errors.append('Number must be an integer')
    if 'type' in data:
        v = (data.get('type') or '').strip() or None
        if v is not None and v not in [c[0] for c in runners.race_type]:
            errors.append('Invalid type')
        else:
            runner_obj.type = v
    if 'shirt_size' in data:
        v = (data.get('shirt_size') or '').strip()
        if not v or v not in [c[0] for c in runners._meta.get_field('shirt_size').choices]:
            errors.append('Invalid shirt size')
        else:
            runner_obj.shirt_size = v
    if 'paid' in data:
        v = data.get('paid')
        if v in (True, 'true', '1', 1):
            runner_obj.paid = True
        elif v in (False, 'false', '0', 0, None, ''):
            runner_obj.paid = False
        else:
            errors.append('Invalid paid value')
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)
    runner_obj.save()
    return JsonResponse({
        'success': True,
        'runner': {
            'id': runner_obj.id,
            'first_name': runner_obj.first_name,
            'last_name': runner_obj.last_name,
            'email': runner_obj.email,
            'age': runner_obj.age,
            'gender': runner_obj.gender or '',
            'number': runner_obj.number,
            'type': runner_obj.type or '',
            'shirt_size': runner_obj.shirt_size,
            'paid': runner_obj.paid,
        }
    })


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
        race_id = request.POST.get('race_id')
        if not race_id:
            return JsonResponse({'success': False, 'message': 'race_id is required.'}, status=400)
        if runner_number is None or (isinstance(runner_number, str) and not runner_number.strip()):
            return JsonResponse({'success': False, 'message': 'runner_number is required.'}, status=400)
        try:
            race_obj = get_object_or_404(race, pk=race_id)
            runner = runners.objects.get(race=race_obj, number=runner_number)
            runner.race_completed = True
            runner.save()
            return JsonResponse({'success': True, 'message': f'Runner {runner_number} marked as finished.'})
        except runners.DoesNotExist:
            return JsonResponse({'success': False, 'message': f'Runner with number {runner_number} not found.'})
        except Exception as e:
            logger.exception('mark_runner_finished failed')
            return JsonResponse({'success': False, 'message': 'An error occurred.'})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})


@login_required
def email_list_view(request):
    """
    Page to send an email to all runners of a selected race. Form: race, subject, body.
    On Send: creates EmailSendJob (queued); background worker sends one email per runner
    with throttling. Confirms that the email has been queued.
    """
    try:
        from .email_queue import start_email_worker
        start_email_worker()
    except Exception as e:
        logger.exception("Failed to start email worker: %s", e)
    races = race.objects.all().order_by('-date', '-scheduled_time')

    if request.method == 'POST':
        data = request.POST
        action = data.get('action')
        if action == 'send':
            try:
                race_ids = data.getlist('race_ids') or ([data.get('race_id')] if data.get('race_id') else [])
                race_ids = [x for x in race_ids if x]
                subject = (data.get('subject') or '').strip()
                body = (data.get('body') or '').strip()
                if not race_ids:
                    return JsonResponse({'success': False, 'error': 'Please select at least one race.'}, status=400)
                if not subject:
                    return JsonResponse({'success': False, 'error': 'Subject is required.'}, status=400)
                unpaid_reminder = data.get('unpaid_reminder') in ('1', 'true', 'yes')
                total_count = 0
                race_objs = []
                for rid in race_ids:
                    try:
                        race_obj = race.objects.get(pk=rid)
                    except (race.DoesNotExist, ValueError):
                        return JsonResponse({'success': False, 'error': f'Invalid race id: {rid}.'}, status=400)
                    race_objs.append(race_obj)
                    if unpaid_reminder:
                        n = race_obj.unpaid_runner_email_count()
                    else:
                        n = race_obj.runner_email_count()
                    total_count += n
                if unpaid_reminder and total_count == 0:
                    return JsonResponse({'success': False, 'error': 'Selected race(s) have no unpaid runners with email addresses.'}, status=400)
                if not unpaid_reminder and total_count == 0:
                    return JsonResponse({'success': False, 'error': 'Selected race(s) have no runners with email addresses.'}, status=400)
                for race_obj in race_objs:
                    EmailSendJob.objects.create(
                        race=race_obj,
                        subject=subject[:255],
                        body=body,
                        unpaid_reminder=unpaid_reminder,
                        status=EmailSendJob.STATUS_QUEUED,
                    )
                num_races = len(race_objs)
                if num_races == 1:
                    msg = f'Your email has been queued and will be sent to {total_count} runner(s).'
                else:
                    msg = f'Your email has been queued for {num_races} race(s) and will be sent to {total_count} runner(s).'
                return JsonResponse({
                    'success': True,
                    'message': msg,
                    'recipient_count': total_count,
                    'num_races': num_races,
                })
            except Exception as e:
                logger.exception('email_list_view send failed')
                return JsonResponse({'success': False, 'error': 'An error occurred. Please try again.'}, status=500)
        if action == 'recipient_count':
            race_ids = data.getlist('race_ids') or ([data.get('race_id')] if data.get('race_id') else [])
            race_ids = [x for x in race_ids if x]
            if not race_ids:
                return JsonResponse({'count': 0})
            unpaid_reminder = data.get('unpaid_reminder') in ('1', 'true', 'yes')
            total = 0
            for rid in race_ids:
                try:
                    race_obj = race.objects.get(pk=rid)
                    total += race_obj.unpaid_runner_email_count() if unpaid_reminder else race_obj.runner_email_count()
                except (race.DoesNotExist, ValueError):
                    pass
            return JsonResponse({'count': total})

    recent_jobs = EmailSendJob.objects.order_by('-created_at')[:10]
    context = {'races': races, 'recent_jobs': recent_jobs}
    return render(request, 'tracker/email_list.html', context)


@login_required
def select_race_for_report(request):
    """Displays the form to select a race and sort order for the printable runner list."""
    form = RunnerInfoSelectionForm()
    context = {'form': form}
    return render(request, 'tracker/select_race_report.html', context)


@login_required
def generate_runner_pdf_report(request):
    """Handles the form submission and generates the PDF report."""
    form = RunnerInfoSelectionForm(request.GET or None)  # Use GET data

    if not form.is_valid():
        # If using GET, invalid data usually means missing parameters.
        # Redirect back or show an error.
        messages.error(request, "Invalid selection. Please select a race and sort order.")
        return redirect('tracker:select_race_report')  # Name this URL pattern

    selected_race = form.cleaned_data['race']
    sort_by = form.cleaned_data['sort_by']

    # Fetch runners for the selected race
    runners_list = runners.objects.filter(race=selected_race)

    # Apply sorting
    if sort_by == 'id':
        runners_list = runners_list.order_by('id')
    elif sort_by == 'last_name':
        runners_list = runners_list.order_by(Lower('last_name'), Lower('first_name'))  # Secondary sort
    elif sort_by == 'first_name':
        runners_list = runners_list.order_by(Lower('first_name'), Lower('last_name'))  # Secondary sort
    elif sort_by == 'number':
        # Handle potential nulls if sorting by number
        runners_list = runners_list.order_by(Coalesce('number', Value(999999)))  # Put nulls last
    elif sort_by == 'paid':
        # Unpaid first, then by last name
        runners_list = runners_list.order_by('paid', Lower('last_name'), Lower('first_name'))
    else:
        # Default sort or raise error if sort_by is unexpected
        runners_list = runners_list.order_by(Lower('last_name'), Lower('first_name'))

    if not runners_list.exists():
        messages.warning(request, f"No runners found for race '{selected_race.name}'.")
        return redirect('tracker:select_race_report')

    # Create PDF
    buffer = io.BytesIO()
    create_runner_pdf(buffer, selected_race, runners_list, sort_by=sort_by)
    buffer.seek(0)  # Reset buffer position to the beginning

    # Create HTTP response
    response = HttpResponse(buffer, content_type='application/pdf')
    # Suggest a filename for the download (sanitized to prevent header injection)
    filename = safe_content_disposition_filename(f"race_{selected_race.id}_runners_{sort_by}") + ".pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    return response


@login_required
def race_summary_pdf_page(request):
    """Dedicated page to select a race and generate the race summary PDF."""
    form = RaceSummaryForm()
    context = {'form': form}
    return render(request, 'tracker/race_summary_pdf.html', context)


@login_required
def generate_race_summary_pdf_report(request):
    """Generates the race summary PDF (finishers by gender, lap stats, placements)."""
    form = RaceSummaryForm(request.GET or None)
    if not form.is_valid():
        messages.error(request, "Please select a race.")
        return redirect('tracker:race_summary_pdf')
    selected_race = form.cleaned_data['race']
    summary_data = _build_race_summary_data(selected_race)
    buffer = io.BytesIO()
    generate_race_summary_pdf(buffer, summary_data)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    filename = "race_summary_" + safe_content_disposition_filename(selected_race.name) + ".pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


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
                time_naive = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
            except (ValueError, TypeError):
                results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "Invalid timestamp format"})
                continue

            try:
                current_time = time_naive.replace(tzinfo=pytz.utc)
                race_obj = race.objects.get(id=race_id)
                rfid_tag_obj = RfidTag.objects.filter(
                    rfid_hex__iexact=runner_rfid_hex.strip()
                ).first()
                if not rfid_tag_obj:
                    results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "Tag not found"})
                    continue
                runner_obj = runners.objects.get(race=race_obj, tag=rfid_tag_obj)

                if race_obj.min_lap_time is None:
                    race_obj.min_lap_time = timedelta(seconds=0)

                # Once runner has completed the race, do not record any more laps
                if runner_obj.race_completed:
                    results.append({"runner_rfid": runner_rfid_hex, "status": "success"})
                    continue

                # Last recorded lap (by lap number); may be lap 0 = chip start
                previous_lap = laps.objects.filter(
                    runner=runner_obj,
                    attach_to_race=race_obj
                ).order_by('-lap').first()

                duration = None
                lap_number = None

                if previous_lap:
                    # Already have at least one crossing (lap 0 or higher). Do not record if under min lap time.
                    if current_time - previous_lap.time <= race_obj.min_lap_time:
                        results.append({"runner_rfid": runner_rfid_hex, "status": "success"})
                        continue
                    # Next counted lap (1 .. laps_count)
                    lap_number = previous_lap.lap + 1
                    # Do not record beyond final lap (defensive)
                    if lap_number > race_obj.laps_count:
                        results.append({"runner_rfid": runner_rfid_hex, "status": "success"})
                        continue
                    duration = current_time - previous_lap.time
                else:
                    # First crossing: if before min_lap_time since gun, record as lap 0 (chip start) only
                    if current_time - race_obj.start_time <= race_obj.min_lap_time:
                        lap0_duration = current_time - race_obj.start_time
                        laps.objects.create(
                            runner=runner_obj,
                            attach_to_race=race_obj,
                            time=current_time,
                            lap=0,
                            duration=lap0_duration,
                            average_speed=0,
                            average_pace=timedelta(0)
                        )
                        results.append({"runner_rfid": runner_rfid_hex, "status": "success"})
                        continue
                    # First crossing after min_lap_time: count as lap 1
                    lap_number = 1
                    duration = current_time - race_obj.start_time

                # Create the counted lap (1 .. laps_count)
                distance_per_lap = race_obj.distance / 1000 / race_obj.laps_count
                speed = (distance_per_lap / duration.total_seconds()) * 3600 * 0.621371
                pace_seconds = ((duration.total_seconds() / 60) / (distance_per_lap / 1.60934)) * 60
                pace = timedelta(seconds=pace_seconds)

                laps.objects.create(
                    runner=runner_obj,
                    attach_to_race=race_obj,
                    time=current_time,
                    lap=lap_number,
                    duration=duration,
                    average_speed=speed,
                    average_pace=pace
                )

                # If this was the final lap, mark runner finished and set gun time + chip time
                if lap_number == race_obj.laps_count:
                    runner_obj.race_completed = True
                    if runner_obj.gender is None:
                        runner_obj.gender = 'male'

                    allfinnisher = runners.objects.filter(race_completed=True, gender=runner_obj.gender)
                    if not allfinnisher.exists():
                        runner_obj.place = 1
                    else:
                        prevfinnisher = allfinnisher.order_by('-place').first()
                        runner_obj.place = (prevfinnisher.place or 0) + 1

                    # Gun time: from race start to finish
                    runner_obj.total_race_time = current_time - race_obj.start_time
                    # Chip time: from first crossing (lap 0) or race start to finish
                    lap0 = laps.objects.filter(
                        runner=runner_obj, attach_to_race=race_obj, lap=0
                    ).first()
                    chip_start = lap0.time if lap0 else race_obj.start_time
                    runner_obj.chip_time = current_time - chip_start

                    totalracetimesecond = runner_obj.total_race_time.total_seconds()
                    kmhtotal = (race_obj.distance / 1000) / (totalracetimesecond / 3600)
                    mphtotal = kmhtotal * 0.621371
                    runner_obj.race_avg_speed = mphtotal
                    avg_pace_seconds = ((runner_obj.total_race_time.total_seconds() / 60) / (
                        race_obj.distance / 1609.34)) * 60
                    runner_obj.race_avg_pace = timedelta(seconds=avg_pace_seconds)
                    runner_obj.save()

                results.append({"runner_rfid": runner_rfid_hex, "status": "success"})

            except runners.DoesNotExist:
                results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "No runner in this race has that tag"})

            except race.DoesNotExist:

                results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "Race not found"})

            except Exception as e:
                logger.exception('record_lap item failed: runner_rfid=%s', runner_rfid_hex)
                results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "Record failed"})

        return JsonResponse({'results': results})

    except Exception as e:
        logger.exception('record_lap request failed')
        return JsonResponse({'error': 'Invalid request.'}, status=400)


@csrf_exempt
@require_api_key
def update_race_time(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    race_id = data.get('race_id')
    action = data.get('action')
    timestamp = data.get('timestamp')

    if not race_id:
        return JsonResponse({'error': 'race_id is required'}, status=400)
    if not timestamp:
        return JsonResponse({'error': 'timestamp is required'}, status=400)
    if not action or action not in ('start', 'stop'):
        return JsonResponse({'error': 'action must be "start" or "stop"'}, status=400)

    try:
        time_naive = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
        current_time = time_naive.replace(tzinfo=pytz.utc)
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid timestamp format'}, status=400)

    race_obj = get_object_or_404(race, id=race_id)

    try:
        if action == 'start':
            if race_obj.status not in ('in_progress', 'completed'):
                race_obj.start_time = current_time
                race_obj.status = 'in_progress'
                race_obj.save()
        elif action == 'stop':
            if race_obj.status != 'completed':
                race_obj.end_time = current_time
                race_obj.status = 'completed'
                race_obj.save()
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)

        return JsonResponse({
            'status': 'success'
        })
    except Exception as e:
        logger.exception('update_race_time failed: %s', e)
        return JsonResponse({'error': 'Invalid request.'}, status=400)


@csrf_exempt
@require_api_key
def update_rfid(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    race_id = data.get('race_id')
    runner_number = data.get('runner_number')
    rfid_tag = (data.get('rfid_tag') or '').strip()

    if not race_id:
        return JsonResponse({'error': 'race_id is required'}, status=400)
    if runner_number is None or runner_number == '':
        return JsonResponse({'error': 'runner_number is required'}, status=400)
    if not rfid_tag:
        return JsonResponse({'error': 'rfid_tag is required'}, status=400)

    race_local = get_object_or_404(race, id=race_id)
    runner_obj = runners.objects.filter(race=race_local, number=runner_number).first()
    if not runner_obj:
        return JsonResponse({'error': 'Runner not found'}, status=404)

    rfid_tag_obj = RfidTag.objects.filter(rfid_hex__iexact=rfid_tag).first()
    if not rfid_tag_obj:
        next_num = (RfidTag.objects.aggregate(max_num=Max('tag_number'))['max_num'] or 0) + 1
        rfid_tag_obj = RfidTag.objects.create(tag_number=next_num, rfid_hex=rfid_tag)

    runner_obj.tag = rfid_tag_obj
    runner_obj.save()
    return JsonResponse({'status': 'success'})


@csrf_exempt
@require_api_key
def assign_tag(request):
    """Assign an existing RFID tag to a runner. Tag must already exist (use update_rfid to create + assign)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    race_id = data.get('race_id')
    runner_number = data.get('runner_number')
    rfid_tag = (data.get('rfid_tag') or '').strip()

    if not race_id:
        return JsonResponse({'error': 'race_id is required'}, status=400)
    if runner_number is None or runner_number == '':
        return JsonResponse({'error': 'runner_number is required'}, status=400)
    if not rfid_tag:
        return JsonResponse({'error': 'rfid_tag is required'}, status=400)

    race_local = get_object_or_404(race, id=race_id)
    runner_obj = runners.objects.filter(race=race_local, number=runner_number).first()
    if not runner_obj:
        return JsonResponse({'error': 'Runner not found'}, status=404)

    rfid_tag_obj = RfidTag.objects.filter(rfid_hex__iexact=rfid_tag).first()
    if not rfid_tag_obj:
        return JsonResponse({'error': 'RFID tag not found with that hex value'}, status=400)

    runner_obj.tag = rfid_tag_obj
    runner_obj.save()
    return JsonResponse({'status': 'success'})


@require_api_key
def get_available_races(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        qs = race.objects.exclude(status__in=['completed']).values('id', 'name', 'status', 'date', 'scheduled_time')
        races = []
        for r in qs:
            races.append({
                'id': r['id'],
                'name': r['name'],
                'status': r['status'],
                'date': r['date'].isoformat() if r.get('date') else None,
                'scheduled_time': r['scheduled_time'].isoformat() if r.get('scheduled_time') else None,
            })
        return JsonResponse({'status': 'success', 'races': races})
    except Exception as e:
        logger.exception('get_available_races failed: %s', e)
        return JsonResponse({'error': 'Invalid request.'}, status=400)


# ----------------------------Site Settings--------------------------------------
@login_required
def site_settings_view(request):
    """Settings page: PayPal on/off and PayPal options."""
    site_settings = SiteSettings.get_settings()
    if request.method == 'POST':
        form = SiteSettingsForm(request.POST, instance=site_settings)
        if form.is_valid():
            form.save()
            messages.success(request, 'Settings saved.')
            return redirect('tracker:site-settings')
    else:
        form = SiteSettingsForm(instance=site_settings)
    return render(request, 'tracker/site_settings.html', {'form': form, 'site_settings': site_settings})


# ----------------------------RFID Tags--------------------------------------
@login_required
def rfid_tags_list(request):
    """List RFID tags and allow adding new ones (and optionally deleting)."""
    if request.method == 'POST':
        delete_id = request.POST.get('delete_id')
        if delete_id:
            try:
                tag = RfidTag.objects.get(pk=delete_id)
                tag.delete()
                messages.success(request, f'RFID tag {tag.tag_number} removed.')
            except RfidTag.DoesNotExist:
                messages.error(request, 'Tag not found.')
            return redirect('tracker:rfid_tags_list')

        tag_number = request.POST.get('tag_number')
        rfid_hex = (request.POST.get('rfid_hex') or '').strip()
        if tag_number is not None and rfid_hex:
            try:
                tag_number = int(tag_number)
                if tag_number < 1:
                    messages.error(request, 'Tag number must be at least 1.')
                else:
                    RfidTag.objects.create(tag_number=tag_number, rfid_hex=rfid_hex)
                    messages.success(request, f'RFID tag {tag_number} added.')
            except ValueError:
                messages.error(request, 'Tag number must be a whole number.')
            except IntegrityError:
                messages.error(request, f'Tag number {tag_number} already exists.')
        else:
            messages.error(request, 'Tag number and RFID hex are required.')
        return redirect('tracker:rfid_tags_list')

    tags = RfidTag.objects.all().order_by('tag_number')
    return render(request, 'tracker/rfid_tags.html', {'tags': tags})


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
        if runners_without_number.exists():
            # Check if there are any numbers already assigned
            existing_numbers = runners.objects.filter(race=race_local, number__isnull=False).values_list('number', flat=True)

            if existing_numbers:
                next_number = max(existing_numbers) + 1
            else:
                next_number = race_local.number_start or 1  # Default to 1 if number_start is None

            for runner in runners_without_number:
                runner.number = next_number
                try:
                    rfid_tag = RfidTag.objects.get(tag_number=next_number)
                    runner.tag = rfid_tag
                except RfidTag.DoesNotExist:
                    runner.tag = None
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
                    'average_pace': timedelta(seconds=round(lap.average_pace.total_seconds())),
                    'average_speed': lap.average_speed
                })

            runner_times.append({
                'number': arunner.number,
                'name': f"{arunner.first_name} {arunner.last_name}",
                'total_race_time': (
                    timedelta(seconds=round(trt.total_seconds()))
                    if (trt := arunner.total_race_time) is not None
                    else "Not Finished"
                ),
                'gun_time': (
                    timedelta(seconds=round(trt.total_seconds()))
                    if (trt := arunner.total_race_time) is not None
                    else None
                ),
                'chip_time': (
                    timedelta(seconds=round(ct.total_seconds()))
                    if (ct := getattr(arunner, 'chip_time', None)) is not None
                    else None
                ),
                'average_pace': (
                    timedelta(seconds=round(trt.total_seconds()))
                    if (trt := arunner.race_avg_pace) is not None
                    else "Not Finished"
                ),
                'average_speed': arunner.race_avg_speed if not None else "Not Finished",
                'place': arunner.place,
                'gender': arunner.gender,
                'type': arunner.type,
                'laps': run_laps

            })

    # Pass the runner times to the template
    context = {
        'runner_times': runner_times,
        'race_name': current_race.name if current_race else "No current race",
        'current_race': current_race,
    }

    return render(request, 'tracker/race_overview.html', context)


def format_timedelta(td):
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


@cache_unless_authenticated(60)
def completed_races_selection(request):
    completed_races = race.objects.filter(status='completed')
    context = {
        'completed_races': completed_races
    }
    return render(request, 'tracker/completed_races_selection.html', context)


def get_completed_race_overview(request, race_id):
    current_race = get_object_or_404(race, id=race_id, status='completed')

    # Initialize an empty list to store runner times
    runner_times = []
    if current_race:
        runnersall = runners.objects.filter(race=current_race).order_by(F('place').asc(nulls_last=True))
        for arunner in runnersall:
            run_laps = []
            alap = laps.objects.filter(runner=arunner).order_by('lap')
            for lap in alap:
                run_laps.append({
                    'lap': lap.lap,
                    'duration': format_timedelta(lap.duration),
                    'average_pace': format_timedelta(lap.average_pace),
                    'average_speed': lap.average_speed
                })
            runner_times.append({
                'number': arunner.number,
                'name': f"{arunner.first_name} {arunner.last_name}",
                'total_race_time': (
                    format_timedelta(td)
                    if (td := arunner.total_race_time) is not None
                    else "Not Finished"
                ),
                'gun_time': (
                    format_timedelta(td)
                    if (td := arunner.total_race_time) is not None
                    else None
                ),
                'chip_time': (
                    format_timedelta(td)
                    if (td := getattr(arunner, 'chip_time', None)) is not None
                    else None
                ),
                'average_pace': (
                    format_timedelta(td)
                    if (td := arunner.race_avg_pace) is not None
                    else "Not Finished"
                ),
                'average_speed': arunner.race_avg_speed if arunner.race_avg_speed is not None else "Not Finished",
                'place': arunner.place,
                'gender': arunner.gender,
                'type': arunner.type,
                'laps': run_laps
            })

    context = {
        'runner_times': runner_times,
        'race_name': current_race.name,
        'race_id': race_id,
    }
    return JsonResponse(context)


def _paypal_custom_for_runner(runner_id):
    """Build signed custom value for PayPal (runner_id + HMAC)."""
    secret = getattr(settings, 'PAYPAL_CUSTOM_SECRET', settings.SECRET_KEY)
    payload = str(runner_id).encode('utf-8')
    sig = hmac.new(secret.encode('utf-8') if isinstance(secret, str) else secret, payload, hashlib.sha256).hexdigest()
    return f"{runner_id}:{sig}"


def _paypal_runner_id_from_custom(custom_value):
    """Verify and extract runner_id from PayPal IPN custom field. Returns runner_id or None."""
    if not custom_value or ':' not in custom_value:
        return None
    runner_id_str, sig = custom_value.strip().split(':', 1)
    try:
        runner_id = int(runner_id_str)
    except ValueError:
        return None
    expected = _paypal_custom_for_runner(runner_id)
    if not hmac.compare_digest(custom_value.strip(), expected):
        return None
    return runner_id


def _paypal_base_url(request):
    """Base URL for PayPal return/cancel/notify. Use PAYPAL_IPN_BASE_URL if set (for local dev with tunnel)."""
    base = getattr(settings, 'PAYPAL_IPN_BASE_URL', None) or ''
    if isinstance(base, str):
        base = base.strip().rstrip('/')
    if base:
        return base
    return request.build_absolute_uri('/').rstrip('/')


def _paypal_post_context(request, runner, race_obj, return_url_extra=None, cancel_url_extra=None):
    """
    Build context for PayPal redirect template: action URL and form params.
    PayPal requires form POST to webscr so that notify_url (IPN) is honored; GET redirects can drop it.
    """
    paypal_email = (getattr(settings, 'PAYPAL_BUSINESS_EMAIL', '') or '').strip()
    entry_fee = float(race_obj.Entry_fee or 0)
    use_sandbox = getattr(settings, 'PAYPAL_SANDBOX', False)
    base_url = 'https://www.sandbox.paypal.com' if use_sandbox else 'https://www.paypal.com'
    paypal_base = _paypal_base_url(request)
    return_path = paypal_base + reverse('tracker:paypal-return')
    cancel_path = paypal_base + reverse('tracker:paypal-cancel')
    if return_url_extra:
        return_path += '?' + urllib.parse.urlencode(return_url_extra)
    if cancel_url_extra:
        cancel_path += '?' + urllib.parse.urlencode(cancel_url_extra)
    notify_url = paypal_base + reverse('tracker:paypal-ipn')
    custom = _paypal_custom_for_runner(runner.id)
    item_name = f"Race entry: {race_obj.name}"
    params = {
        'cmd': '_donations',
        'business': paypal_email,
        'amount': f'{entry_fee:.2f}',
        'currency_code': 'USD',
        'item_name': item_name[:127],
        'return': return_path,
        'cancel_return': cancel_path,
        'notify_url': notify_url,
        'custom': custom[:256],
    }
    return {
        'paypal_action': base_url + '/cgi-bin/webscr',
        'paypal_params': params,
    }


def _pay_link_for_runner(runner):
    """Build the pay-later URL for a runner, or None if site_base_url is not set."""
    site_settings = SiteSettings.get_settings()
    base = (site_settings.site_base_url or '').strip().rstrip('/')
    if not base:
        return None
    custom = _paypal_custom_for_runner(runner.id)
    _, signature = custom.split(':', 1)
    path = reverse('tracker:pay-entry', args=[runner.id, signature])
    return base + path


def send_signup_confirmation_email(runner):
    """
    Send a single signup confirmation email to the runner.
    If paid: confirm signup and payment. If not paid: confirm signup and include pay link if site_base_url is set.
    Marks runner.signup_confirmation_sent = True.
    """
    if not runner.email or (runner.email or '').strip() == '':
        runner.signup_confirmation_sent = True
        runner.save(update_fields=['signup_confirmation_sent'])
        return
    race_obj = runner.race
    race_name = race_obj.name
    race_date = race_obj.date
    race_time = race_obj.scheduled_time
    entry_fee = float(race_obj.Entry_fee or 0)
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', 'noreply@example.com')
    subject = f"Signup confirmed: {race_name}"
    if runner.paid:
        body = f"Hi {runner.first_name},\n\nYou're signed up for {race_name}."
        if race_date:
            body += f" The race is on {race_date}"
            if race_time:
                body += f" at {race_time}"
            body += "."
        body += "\n\nYour payment has been received. See you on race day!"
    else:
        body = f"Hi {runner.first_name},\n\nYou're signed up for {race_name}."
        if race_date:
            body += f" The race is on {race_date}"
            if race_time:
                body += f" at {race_time}"
            body += "."
        if entry_fee > 0:
            body += f"\n\nThe entry fee is ${entry_fee:.2f}."
            pay_link = _pay_link_for_runner(runner)
            if pay_link:
                body += f"\n\nIf you haven't paid yet, you can pay here: {pay_link}"
            body += "\n\nYou can also pay on race day when you check in."
        body += "\n\nSee you on race day!"
    body += "\n\n---\nThis is an unmonitored email account. Please do not reply."
    send_mail(
        subject=subject,
        message=body,
        from_email=from_email,
        recipient_list=[runner.email],
        fail_silently=False,
    )
    runner.signup_confirmation_sent = True
    runner.save(update_fields=['signup_confirmation_sent'])


def race_signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            selected_race = form.cleaned_data['race']
            runner = form.save()
            site_settings = SiteSettings.get_settings()
            paypal_email = (getattr(settings, 'PAYPAL_BUSINESS_EMAIL', '') or '').strip()
            entry_fee = float(selected_race.Entry_fee or 0)
            if site_settings.paypal_enabled and paypal_email and entry_fee > 0:
                # POST to PayPal so notify_url (IPN) is honored; GET redirects can drop it per PayPal docs.
                sig = _paypal_custom_for_runner(runner.id).split(':', 1)[1]
                extra = {'runner_id': runner.id, 'sig': sig}
                context = _paypal_post_context(request, runner, selected_race, return_url_extra=extra, cancel_url_extra=extra)
                return render(request, 'tracker/paypal_redirect.html', context)
            # No PayPal: send signup confirmation immediately
            send_signup_confirmation_email(runner)
            return redirect(reverse('tracker:signup-success', args=[selected_race.id]))
    else:
        form = SignupForm()
    current_races = race.objects.filter(status='signup_open').order_by('date', 'scheduled_time')
    banners = Banner.objects.active_for_page(Banner.PAGE_SIGNUP)
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


def paypal_return(request):
    """Shown after user completes (or abandons) PayPal. Payment is normally confirmed via IPN.
    When we have runner_id+sig in the URL (from our redirect), we treat the return as proof of payment:
    mark runner paid if not already, and send confirmation email if not already sent.
    This covers both (1) IPN ran but email failed and (2) IPN never reached us (e.g. localhost).
    """
    rid_get = request.GET.get('runner_id')
    sig_get = (request.GET.get('sig') or '').strip()
    if rid_get and sig_get:
        try:
            rid = int(rid_get)
        except (TypeError, ValueError):
            rid = None
        if rid is not None and _paypal_runner_id_from_custom(f"{rid}:{sig_get}") == rid:
            runner = runners.objects.filter(pk=rid).first()
            if runner:
                if not runner.paid:
                    runner.paid = True
                    runner.save(update_fields=['paid'])
                if not runner.signup_confirmation_sent:
                    send_signup_confirmation_email(runner)
    return render(request, 'tracker/paypal_return.html')


def paypal_cancel(request):
    """Shown when user cancels PayPal payment. Runner remains registered but unpaid.
    Sends signup confirmation email automatically (with pay-later link). Only GET; no form.
    """
    if request.GET.get('sent') == '1':
        return render(request, 'tracker/paypal_cancel.html', {'sent': True})

    runner = None
    session_id = request.session.get('paypal_pending_runner_id')
    if session_id is not None:
        runner = runners.objects.filter(pk=session_id).first()
        if runner:
            request.session.pop('paypal_pending_runner_id', None)
    if runner is None:
        rid_get = request.GET.get('runner_id')
        sig_get = (request.GET.get('sig') or '').strip()
        if rid_get and sig_get:
            try:
                rid = int(rid_get)
            except (TypeError, ValueError):
                rid = None
            if rid is not None and _paypal_runner_id_from_custom(f"{rid}:{sig_get}") == rid:
                runner = runners.objects.filter(pk=rid).first()

    if runner is not None:
        # Only send if they haven't already had one (e.g. they came from pay-later link and already got the email)
        if not runner.signup_confirmation_sent:
            send_signup_confirmation_email(runner)
            return redirect(reverse('tracker:paypal-cancel') + '?sent=1')

    return render(request, 'tracker/paypal_cancel.html', {'sent': False})


@csrf_exempt
def paypal_ipn(request):
    """
    PayPal IPN (Instant Payment Notification). PayPal POSTs here when a payment completes.
    Verify the request with PayPal, then mark the runner as paid if payment_status=Completed.
    """
    import logging
    logger = logging.getLogger(__name__)
    if request.method != 'POST':
        return HttpResponse(status=405)
    raw_body = request.body
    if not raw_body:
        return HttpResponse('ok')
    site_settings = SiteSettings.get_settings()
    use_sandbox = getattr(settings, 'PAYPAL_SANDBOX', False)
    paypal_url = 'https://ipnpb.sandbox.paypal.com/cgi-bin/webscr' if use_sandbox else 'https://ipnpb.paypal.com/cgi-bin/webscr'
    # PayPal spec: PREFIX the message with cmd=_notify-validate (do not append)
    verify_data = b'cmd=_notify-validate&' + raw_body
    try:
        import urllib.request
        req = urllib.request.Request(
            paypal_url,
            data=verify_data,
            method='POST',
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'User-Agent': 'Simple5K-IPN-Listener',
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            verify_result = resp.read().decode('utf-8').strip()
    except Exception as e:
        logger.exception('PayPal IPN verification request failed: %s', e)
        return HttpResponse(status=500)
    if verify_result != 'VERIFIED':
        logger.warning('PayPal IPN verification failed: result=%r', verify_result)
        return HttpResponse(status=400)
    # Parse body for our use (latin-1 never fails on any byte)
    try:
        body_str = raw_body.decode('utf-8')
    except UnicodeDecodeError:
        body_str = raw_body.decode('latin-1')
    data = urllib.parse.parse_qs(body_str)
    payment_status = (data.get('payment_status') or [''])[0]
    custom = (data.get('custom') or [''])[0]
    if payment_status.lower() not in ('completed', 'processed'):
        logger.info('PayPal IPN ignored: payment_status=%r', payment_status)
        return HttpResponse('ok')
    runner_id = _paypal_runner_id_from_custom(custom)
    if runner_id is None:
        logger.warning('PayPal IPN: invalid or missing custom field')
        return HttpResponse('ok')
    try:
        runner_obj = runners.objects.get(pk=runner_id)
        runner_obj.paid = True
        runner_obj.save(update_fields=['paid'])
        if not runner_obj.signup_confirmation_sent:
            send_signup_confirmation_email(runner_obj)
        logger.info('PayPal IPN processed: runner_id=%s marked paid', runner_id)
    except runners.DoesNotExist:
        logger.warning('PayPal IPN: runner_id=%s not found', runner_id)
    return HttpResponse('ok')


def pay_entry(request, runner_id, signature):
    """
    Pay-later page: valid link from signup confirmation email. Verifies runner_id + signature
    then redirects to PayPal with the same flow as at signup.
    """
    custom = f"{runner_id}:{signature}"
    if _paypal_runner_id_from_custom(custom) != runner_id:
        raise Http404("Invalid or expired pay link.")
    try:
        runner_obj = runners.objects.get(pk=runner_id)
    except runners.DoesNotExist:
        raise Http404("Runner not found.")
    if runner_obj.paid:
        return redirect(reverse('tracker:signup-success', args=[runner_obj.race_id]))
    site_settings = SiteSettings.get_settings()
    paypal_email = (getattr(settings, 'PAYPAL_BUSINESS_EMAIL', '') or '').strip()
    race_obj = runner_obj.race
    entry_fee = float(race_obj.Entry_fee or 0)
    if not site_settings.paypal_enabled or not paypal_email or entry_fee <= 0:
        return redirect(reverse('tracker:signup-success', args=[race_obj.id]))
    extra = {'runner_id': runner_obj.id, 'sig': signature}
    context = _paypal_post_context(request, runner_obj, race_obj, return_url_extra=extra, cancel_url_extra=extra)
    return render(request, 'tracker/paypal_redirect.html', context)


def race_countdown(request):
    """Get countdown for all upcoming races along with active race information"""
    # Get races that haven't started yet (status is signup_open or signup_closed)
    upcoming_races = race.objects.filter(status__in=['signup_open', 'signup_closed']).order_by('date', 'scheduled_time')
    # Check for an active race
    active_race = race.objects.filter(status='in_progress').first()
    active_race_data = None

    if active_race:
        active_race_data = {
            'id': active_race.id,
            'name': active_race.name,
        }
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
    return JsonResponse({'races': race_data, 'active_race': active_race_data}, safe=False)  # Return json in dictionary structure


def race_list(request):
    """Render the race list page."""
    banners = Banner.objects.active_for_page(Banner.PAGE_HOME)
    return render(request, 'tracker/race_list.html', context={'banners': banners})
