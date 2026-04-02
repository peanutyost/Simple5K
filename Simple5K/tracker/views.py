from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.db import IntegrityError, transaction
from django.db.models import F, Q, Window, IntegerField, OrderBy, Value
from django.db.models.functions import Rank, DenseRank, Lower, Coalesce
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
from django.core.validators import EmailValidator
from django.conf import settings
from decimal import Decimal
from functools import wraps
import hmac
import hashlib
import io
import json
import logging
import pytz

logger = logging.getLogger(__name__)

from .models import race, runners, laps, Banner, ApiKey, RfidTag, SiteSettings, EmailSendJob, PayPalOrder
from .forms import LapForm, raceStart, runnerStats, SignupForm, RaceForm, RaceSelectionForm, RunnerInfoSelectionForm, RaceSummaryForm, SiteSettingsForm, BannerForm
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


def calculate_age_bracket_placement_in_gender(runner, race_obj):
    """
    Calculates a runner's placement within their age bracket and gender for a given race.
    Used for the race summary PDF so men and women are ranked per age group separately.

    Returns:
        The runner's placement within their (age bracket, gender), or None if not available.
    """
    if runner.total_race_time is None or not runner.gender:
        return None
    same_bracket_same_gender = runners.objects.filter(
        race=race_obj,
        age=runner.age,
        gender=runner.gender,
        total_race_time__isnull=False,
    ).annotate(
        rank=Window(
            expression=Rank(),
            partition_by=[F('age'), F('gender')],
            order_by='total_race_time',
        )
    ).values('pk', 'rank')
    try:
        return next(
            (item['rank'] for item in same_bracket_same_gender if item['pk'] == runner.pk),
            None,
        )
    except StopIteration:
        return None


def _build_race_summary_data(race_obj):
    """Build summary data for race summary PDF: finishers by gender with lap stats and placements."""
    # Order by finish time and annotate with overall place (across both genders).
    # DenseRank means two runners with the same time share a place and the next place is not skipped.
    finishers = runners.objects.filter(
        race=race_obj,
        total_race_time__isnull=False
    ).annotate(
        overall_rank=Window(
            expression=DenseRank(),
            order_by=F('total_race_time').asc(),
        )
    ).order_by('total_race_time')
    females = []
    males = []
    for runner in finishers:
        runner_laps = list(laps.objects.filter(runner=runner).order_by('lap'))
        # Exclude lap 0 (chip start) when computing fastest/slowest
        running_laps = [l for l in runner_laps if l.lap != 0]
        if running_laps:
            fastest = min(running_laps, key=lambda l: l.duration)
            slowest = max(running_laps, key=lambda l: l.duration)
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
            'overall_place': runner.overall_rank,
            'age_group': runner.get_age_display() if runner.age else None,
            'age_group_place': calculate_age_bracket_placement_in_gender(runner, race_obj),
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
    try:
        logo_path = race_obj.logo.path if race_obj.logo else ''
    except (ValueError, OSError):
        logo_path = ''  # File missing from storage
    race_info = {
        'name': race_obj.name,
        'date': race_obj.date.strftime('%Y-%m-%d'),
        'distance': race_obj.distance,
        'logo': logo_path,
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

    # Lap Data (use duration for "Lap time" column; lap.time is clock time, lap.duration is elapsed time; exclude lap 0)
    laps_data = []
    for lap in laps.objects.filter(runner=runner_obj).order_by('lap'):
        if lap.lap == 0:
            continue
        dur = getattr(lap, 'duration', None)
        speed = getattr(lap, 'average_speed', None)
        pace = getattr(lap, 'average_pace', None)
        laps_data.append({
            'lap': lap.lap,
            'time': str(timedelta(seconds=round(dur.total_seconds()))) if dur else 'N/A',
            'duration': str(dur) if dur is not None else 'N/A',
            'average_speed': float(speed) if speed is not None else 0,
            'average_pace': str(timedelta(seconds=round(pace.total_seconds()))) if pace else 'N/A',
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
        ).order_by('total_race_time')[:2]

        def format_runner(runner):
            return [runner.first_name + ' ' + runner.last_name, f"{str(timedelta(seconds=round(runner.total_race_time.total_seconds())))}"] if runner else "N/A"

        competitor_data = {
            'faster_runners': [format_runner(runner) for runner in faster_runners],
            'slower_runners': [format_runner(runner) for runner in slower_runners],
        }

    # Total finishers and overall place (by finish time; place field on runner is gender place)
    finishers = runners.objects.filter(race=race_obj).exclude(total_race_time__isnull=True)
    total_finishers = finishers.count()
    overall_place = None
    if runner_obj.total_race_time is not None:
        faster_count = finishers.filter(total_race_time__lt=runner_obj.total_race_time).count()
        overall_place = faster_count + 1
    runner_details['overall_place'] = overall_place  # used for PDF "Overall" row
    runner_details['total_finishers'] = total_finishers

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
    # Generate the PDF; sanitize attachment filename to prevent header injection
    safe_name = safe_content_disposition_filename(
        f"{race_obj.name}_{runner_obj.first_name}_{runner_obj.last_name}"
    )
    pdf_filename = f"race_report_{safe_name}.pdf"
    if not pdf_filename.endswith('.pdf'):
        pdf_filename += '.pdf'
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

        # Attach the PDF directly from the bytes (filename already sanitized above)
        email.attach(pdf_filename, pdf_content, "application/pdf")  # Attach the report
        # If you're using Microsoft 365 and have configured TLS settings:
        # email.fail_silently = False  # Raise exceptions on email sending failures
        # Send the email
        try:
            email.send()  # Actually sends the email.

        except Exception as e:
            logger.exception("Error sending email for runner pk=%s", runner_obj.pk)
            raise  # Re-raise to alert the caller

    except Exception as e:
        logger.exception("Error processing or sending race report for runner pk=%s", runner_obj.pk)
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
    queryset = race.objects.filter(archived=False)
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
            lv = form.cleaned_data['racename']  # ModelChoiceField returns the race instance
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
            raceobj = form.cleaned_data['racename']
            try:
                runnerobj = runners.objects.get(number=form.cleaned_data['runnernumber'], race=raceobj)
            except runners.DoesNotExist:
                messages.error(request, f"No runner with number {form.cleaned_data['runnernumber']} found for this race.")
                return render(request, 'tracker/runner_stats.html', context=context)
            racetotalobj = prepare_race_data(raceobj, runnerobj)
        else:
            return render(request, 'tracker/runner_stats.html', context=context)
        filename = f"race_report_{raceobj.name}_{runnerobj.first_name}_{runnerobj.last_name}.pdf"
        response = generate_race_report(filename, racetotalobj, "response")
        return response

    return render(request, 'tracker/runner_stats.html', context=context)


@login_required
def select_race(request):
    # Get all races where status is either 'signup_open' or 'signup_closed' (exclude archived)
    races = race.objects.filter(
        Q(status='signup_open') | Q(status='signup_closed'),
        archived=False,
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
        Q(status='signup_open') | Q(status='signup_closed') | Q(status='in_progress') | Q(status='completed'),
        archived=False,
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
    rfid_tags = RfidTag.objects.all().order_by('tag_number')
    # Build runner choices as JSON in the view so the template always gets valid JSON (dropdowns work)
    def choice_list(choices, empty_option=False):
        items = [{'value': str(v), 'label': str(l)} for v, l in choices]
        if empty_option:
            items = [{'value': '', 'label': '—'}] + items
        return items
    runner_choices = {
        'age_brackets': choice_list(runners.age_bracket),
        'genders': choice_list(runners._meta.get_field('gender').choices),
        'race_types': choice_list(runners.race_type, empty_option=True),
        'shirt_sizes': choice_list(runners._meta.get_field('shirt_size').choices),
        'tags': [{'value': '', 'label': '—'}] + [{'value': str(t.id), 'label': str(t)} for t in rfid_tags],
    }
    context = {
        'race': selected_race,
        'runners': race_runners,
        'age_brackets': runners.age_bracket,
        'genders': runners._meta.get_field('gender').choices,
        'race_types': runners.race_type,
        'shirt_sizes': runners._meta.get_field('shirt_size').choices,
        'rfid_tags': rfid_tags,
        'runner_choices': runner_choices,
        # Path-only URLs so fetch() uses the current page origin (HTTPS when page is HTTPS)
        'add_runner_url': reverse('tracker:add_runner'),
        'edit_runner_url': reverse('tracker:edit_runner'),
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
        # Lock the race row to prevent concurrent auto-assign from producing duplicate numbers
        with transaction.atomic():
            race.objects.select_for_update().filter(pk=race_obj.pk).first()
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
    else:
        try:
            EmailValidator()(email)
        except Exception:
            errors.append('Enter a valid email address')
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

    send_confirmation_email = data.get('send_confirmation_email') in (True, 'true', 'True', 1, '1')

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
        send_signup_confirmation=send_confirmation_email,
    )
    if send_confirmation_email and runner_obj.email and (runner_obj.email or '').strip():
        send_signup_confirmation_email(runner_obj)
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
            try:
                EmailValidator()(v)
            except Exception:
                errors.append('Enter a valid email address')
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
    if 'tag_id' in data:
        v = data.get('tag_id')
        if v is None or v == '':
            runner_obj.tag_id = None
        else:
            try:
                tag_pk = int(v)
                tag_obj = RfidTag.objects.filter(pk=tag_pk).first()
                if not tag_obj:
                    errors.append('RFID tag not found')
                else:
                    other = runners.objects.filter(race_id=runner_obj.race_id, tag_id=tag_pk).exclude(pk=runner_obj.pk).first()
                    if other:
                        errors.append(
                            'That RFID tag is already assigned to another runner in this race. '
                            'Each tag can only be used by one runner per race.'
                        )
                    else:
                        runner_obj.tag_id = tag_pk
            except (TypeError, ValueError):
                errors.append('Invalid tag_id')
    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)
    runner_obj.save()
    tag_display = ''
    tag_id = None
    if runner_obj.tag_id:
        tag_id = runner_obj.tag_id
        tag_display = str(runner_obj.tag)
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
            'tag_id': tag_id,
            'tag_display': tag_display,
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
    races = race.objects.filter(archived=False).order_by('-date', '-scheduled_time')

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

        MAX_BATCH_SIZE = 500
        if len(laps_data) > MAX_BATCH_SIZE:
            return JsonResponse({'error': f'Maximum {MAX_BATCH_SIZE} laps per request'}, status=400)

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
                try:
                    time_naive = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
                except ValueError:
                    time_naive = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')
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

                if race_obj.start_time is None:
                    results.append({"runner_rfid": runner_rfid_hex, "status": "failed", "error": "Race has not started"})
                    continue
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
                # distance in meters; per-lap distance in km for speed (km/h then to mph)
                distance_meters = float(race_obj.distance)
                lap_distance_km = (distance_meters / 1000.0) / race_obj.laps_count
                lap_distance_miles = lap_distance_km / 1.60934
                secs = duration.total_seconds()
                if secs > 0 and lap_distance_miles > 0:
                    # speed: mph = (lap_miles) / (secs/3600)
                    speed = (lap_distance_miles * 3600) / secs
                    # pace: seconds per mile (for timedelta)
                    pace_seconds = secs * 1609.34 / (lap_distance_km * 1000) if lap_distance_km > 0 else 0
                    pace = timedelta(seconds=pace_seconds)
                else:
                    speed = 0
                    pace = timedelta(0)

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

                    # Use transaction + select_for_update to prevent race condition on place assignment.
                    # Lock the race row so only one finisher can be processed at a time.
                    # Filter place__isnull=False so runners marked as dropped out (race_completed=True
                    # but no place assigned) don't corrupt the place sequence.
                    with transaction.atomic():
                        race.objects.select_for_update().get(id=race_obj.id)
                        allfinnisher = (
                            runners.objects
                            .filter(
                                race=race_obj,
                                race_completed=True,
                                gender=runner_obj.gender,
                                place__isnull=False,
                            )
                        )
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

                        # Avg speed (mph) and pace (sec/mile): use chip time when available (runner's actual time over distance)
                        time_for_calc = runner_obj.chip_time if runner_obj.chip_time else runner_obj.total_race_time
                        total_seconds = time_for_calc.total_seconds()
                        distance_meters = float(race_obj.distance)
                        if total_seconds > 0 and distance_meters > 0:
                            distance_miles = distance_meters / 1609.34
                            # speed_mph = distance_miles / time_hours
                            runner_obj.race_avg_speed = (distance_miles * 3600) / total_seconds
                            # pace: seconds per mile (for timedelta display as min:sec per mile)
                            runner_obj.race_avg_pace = timedelta(seconds=total_seconds * 1609.34 / distance_meters)
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
        try:
            time_naive = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S.%fZ')
        except ValueError:
            time_naive = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%SZ')
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
def create_rfid(request):
    """Create a new RFID tag. Send name, number (tag_number), and rfid_tag (hex). Then use assign-tag to assign to a runner."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    name = (data.get('name') or '').strip()
    number = data.get('number')
    rfid_hex = (data.get('rfid_tag') or '').strip()

    if number is None or number == '':
        return JsonResponse({'error': 'number is required'}, status=400)
    if not rfid_hex:
        return JsonResponse({'error': 'rfid_tag is required'}, status=400)

    try:
        tag_number = int(number)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'number must be an integer'}, status=400)
    if tag_number < 1:
        return JsonResponse({'error': 'number must be at least 1'}, status=400)

    if RfidTag.objects.filter(tag_number=tag_number).exists():
        return JsonResponse({'error': f'Tag number {tag_number} already exists'}, status=400)
    if RfidTag.objects.filter(rfid_hex__iexact=rfid_hex).exists():
        return JsonResponse({'error': 'An RFID tag with that hex value already exists'}, status=400)

    RfidTag.objects.create(name=name or '', tag_number=tag_number, rfid_hex=rfid_hex)
    return JsonResponse({'status': 'success'})


@csrf_exempt
@require_api_key
def assign_tag(request):
    """Assign an existing RFID tag to a runner. Tag must already exist (use create-rfid to create a tag first)."""
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

    # One tag per race: ensure no other runner in this race has this tag (allow reassigning to same runner)
    other = runners.objects.filter(race=race_local, tag=rfid_tag_obj).exclude(pk=runner_obj.pk).first()
    if other:
        return JsonResponse({
            'error': 'That RFID tag is already assigned to another runner in this race (e.g. bib {}). '
                     'Each tag can only be assigned to one runner per race.'.format(other.number or other.id)
        }, status=400)

    runner_obj.tag = rfid_tag_obj
    runner_obj.save()
    return JsonResponse({'status': 'success'})


@require_api_key
def get_available_races(request):
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        qs = race.objects.exclude(status__in=['completed']).filter(archived=False).values('id', 'name', 'status', 'date', 'scheduled_time')
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
        form = SiteSettingsForm(request.POST, request.FILES, instance=site_settings)
        if form.is_valid():
            form.save()
            messages.success(request, 'Settings saved.')
            return redirect('tracker:site-settings')
    else:
        form = SiteSettingsForm(instance=site_settings)
    return render(request, 'tracker/site_settings.html', {'form': form, 'site_settings': site_settings})


# ----------------------------Banners--------------------------------------
@login_required
def banner_list(request):
    """List all banners; links to add and edit."""
    banners = Banner.objects.all().order_by('id')
    return render(request, 'tracker/banner_list.html', {'banners': banners})


@login_required
def banner_create(request):
    """Create a new banner."""
    if request.method == 'POST':
        form = BannerForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Banner created.')
            return redirect('tracker:banner-list')
    else:
        form = BannerForm(initial={'background_color': '#ffffff'})
    return render(request, 'tracker/banner_form.html', {'form': form, 'banner': None})


@login_required
def banner_edit(request, pk):
    """Edit an existing banner."""
    banner = get_object_or_404(Banner, pk=pk)
    if request.method == 'POST':
        form = BannerForm(request.POST, request.FILES, instance=banner)
        if form.is_valid():
            form.save()
            messages.success(request, 'Banner updated.')
            return redirect('tracker:banner-list')
    else:
        form = BannerForm(instance=banner)
    return render(request, 'tracker/banner_form.html', {'form': form, 'banner': banner})


@login_required
def banner_delete(request, pk):
    """Delete a banner (POST only)."""
    banner = get_object_or_404(Banner, pk=pk)
    if request.method == 'POST':
        title = str(banner)
        banner.delete()
        messages.success(request, f'Banner "{title}" deleted.')
        return redirect('tracker:banner-list')
    return redirect('tracker:banner-list')


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

        name = (request.POST.get('name') or '').strip()
        tag_number = request.POST.get('tag_number')
        rfid_hex = (request.POST.get('rfid_hex') or '').strip()
        if tag_number is not None and rfid_hex:
            try:
                tag_number = int(tag_number)
                if tag_number < 1:
                    messages.error(request, 'Tag number must be at least 1.')
                else:
                    RfidTag.objects.create(name=name, tag_number=tag_number, rfid_hex=rfid_hex)
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
            response = render(request, 'tracker/generate_api_key.html', {'api_key': api_key})
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response['Pragma'] = 'no-cache'
            return response
    return render(request, 'tracker/generate_api_key.html')


# ----------------------------Assign numbers--------------------------------------
def _assign_numbers_preview(race_local, starting_tag):
    """Return dict with next_tag_number (next unused tag >= starting_tag) and unassigned_count."""
    tags_in_use = set(
        runners.objects.filter(race=race_local).exclude(tag__isnull=True).values_list('tag_id', flat=True)
    )
    next_tag = (
        RfidTag.objects.exclude(pk__in=tags_in_use)
        .filter(tag_number__gte=starting_tag)
        .order_by('tag_number')
        .first()
    )
    unassigned_count = runners.objects.filter(
        race=race_local, number__isnull=True, tag__isnull=True
    ).count()
    return {
        'next_tag_number': next_tag.tag_number if next_tag else None,
        'unassigned_count': unassigned_count,
    }


@login_required
def assign_numbers(request):
    races = race.objects.exclude(status='in_progress').exclude(status='completed').filter(archived=False)

    if request.method == 'POST':
        race_id = request.POST.get('race')
        race_local = get_object_or_404(race, id=race_id)

        try:
            starting_tag = int(request.POST.get('starting_tag') or 1)
        except (TypeError, ValueError):
            starting_tag = 1
        if starting_tag < 1:
            starting_tag = 1

        runners_unassigned = runners.objects.filter(
            race=race_local, number__isnull=True, tag__isnull=True
        ).order_by('id')
        if runners_unassigned.exists():
            tags_in_use = set(
                runners.objects.filter(race=race_local).exclude(tag__isnull=True).values_list('tag_id', flat=True)
            )
            available_tags = list(
                RfidTag.objects.exclude(pk__in=tags_in_use)
                .filter(tag_number__gte=starting_tag)
                .order_by('tag_number')
            )
            existing_numbers = set(
                runners.objects.filter(race=race_local, number__isnull=False).values_list('number', flat=True)
            )
            assigned_numbers = set()
            assigned_with_tag = 0
            assigned_no_tag = 0

            try:
                with transaction.atomic():
                    for i, runner in enumerate(runners_unassigned):
                        if i < len(available_tags):
                            tag = available_tags[i]
                            runner.number = tag.tag_number
                            runner.tag = tag
                            assigned_numbers.add(tag.tag_number)
                            assigned_with_tag += 1
                            runner.save()
                        else:
                            break
            except IntegrityError:
                messages.error(
                    request,
                    'Cannot assign: one of these RFID tags is already assigned to another runner in this race. '
                    'Each tag can only be used by one runner per race. Fix duplicate tag assignments and try again.'
                )
                assign_preview = _assign_numbers_preview(race_local, starting_tag)
                return render(request, 'tracker/assign_numbers.html', {
                    'races': races,
                    'form': RaceSelectionForm(),
                    'assign_preview': assign_preview,
                    'selected_race_id': str(race_id),
                    'starting_tag': starting_tag,
                })

            remaining = runners_unassigned.count() - assigned_with_tag
            if remaining == 0:
                messages.success(
                    request,
                    f'Assigned {assigned_with_tag} runner(s): runner number = tag number for each. You can run again to assign the next batch.'
                )
            else:
                messages.warning(
                    request,
                    f'Assigned {assigned_with_tag} runner(s). Stopped: not enough unused tags for the remaining {remaining} runner(s). Add more tags and run again.'
                )
            return redirect(reverse('tracker:assign_numbers') + f'?race={race_id}&starting_tag={starting_tag}')
        else:
            assign_preview = _assign_numbers_preview(race_local, starting_tag)
            error_message = (
                "No runners left to assign: every runner already has a number and a tag, "
                "or there are no runners in this race."
            )
            return render(request, 'tracker/assign_numbers.html', {
                'races': races,
                'form': RaceSelectionForm(),
                'error_message': error_message,
                'assign_preview': assign_preview,
                'selected_race_id': str(race_id),
                'starting_tag': starting_tag,
            })

    # GET: optional ?race=id and ?starting_tag=N
    selected_race_id = request.GET.get('race')
    try:
        starting_tag = int(request.GET.get('starting_tag') or 1)
    except (TypeError, ValueError):
        starting_tag = 1
    if starting_tag < 1:
        starting_tag = 1

    assign_preview = None
    if selected_race_id:
        try:
            race_local = race.objects.get(id=selected_race_id)
            assign_preview = _assign_numbers_preview(race_local, starting_tag)
        except (race.DoesNotExist, ValueError):
            pass

    return render(request, 'tracker/assign_numbers.html', {
        'races': races,
        'form': RaceSelectionForm(),
        'assign_preview': assign_preview,
        'selected_race_id': selected_race_id or '',
        'starting_tag': starting_tag,
    })


# ---------------------------Public Views------------------------------------------


@cache_unless_authenticated(60)
def race_overview(request):
    current_race = race.objects.filter(status='in_progress', archived=False).first()

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
                if lap.lap == 0:
                    continue  # exclude chip start from lap list
                lap_dur = getattr(lap, 'duration', None)
                lap_pace = getattr(lap, 'average_pace', None)
                lap_speed = getattr(lap, 'average_speed', None)
                run_laps.append({
                    'lap': lap.lap,
                    'duration': timedelta(seconds=round(lap_dur.total_seconds())) if lap_dur else timedelta(0),
                    'average_pace': timedelta(seconds=round(lap_pace.total_seconds())) if lap_pace else timedelta(0),
                    'average_speed': lap_speed
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
                'average_speed': arunner.race_avg_speed if arunner.race_avg_speed is not None else "Not Finished",
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
    if td is None:
        return "—"
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"


@cache_unless_authenticated(60)
def completed_races_selection(request):
    completed_races = race.objects.filter(status='completed', hidden_from_past_races=False)
    context = {
        'completed_races': completed_races
    }
    return render(request, 'tracker/completed_races_selection.html', context)


def get_completed_race_overview(request, race_id):
    try:
        try:
            current_race = race.objects.get(id=race_id, status='completed')
        except race.DoesNotExist:
            return JsonResponse(
                {'error': 'Race not found.', 'runner_times': [], 'race_name': '', 'race_id': race_id},
                status=404
            )

        runner_times = []
        try:
            runnersall = runners.objects.filter(race=current_race).order_by(F('place').asc(nulls_last=True))
        except (TypeError, AttributeError):
            runnersall = runners.objects.filter(race=current_race).order_by('place')

        for arunner in runnersall:
            run_laps = []
            alap = laps.objects.filter(runner=arunner).order_by('lap')
            for lap in alap:
                if lap.lap == 0:
                    continue  # exclude chip start from lap list
                run_laps.append({
                    'lap': lap.lap,
                    'duration': format_timedelta(lap.duration) if lap.duration is not None else "—",
                    'average_pace': format_timedelta(lap.average_pace) if lap.average_pace is not None else "—",
                    'average_speed': float(lap.average_speed) if lap.average_speed is not None else "—",
                })
            name = f"{(arunner.first_name or '')} {(arunner.last_name or '')}".strip() or "—"
            avg_speed = arunner.race_avg_speed
            if avg_speed is not None and hasattr(avg_speed, '__float__'):
                avg_speed = float(avg_speed)
            runner_times.append({
                'number': arunner.number,
                'name': name,
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
                'average_speed': avg_speed if avg_speed is not None else "Not Finished",
                'place': arunner.place,
                'gender': arunner.gender or None,
                'type': arunner.type or None,
                'laps': run_laps
            })

        context = {
            'runner_times': runner_times,
            'race_name': current_race.name,
            'race_id': race_id,
        }
        return JsonResponse(context)
    except Exception as e:
        logger.exception("get_completed_race_overview failed for race_id=%s", race_id)
        return JsonResponse(
            {'error': 'Unable to load results. Please try again.', 'runner_times': [], 'race_name': '', 'race_id': race_id},
            status=500
        )


def _paypal_sign_runner_id(runner_id):
    """Build HMAC signature for runner_id (used for pay-later link authentication)."""
    secret = settings.SECRET_KEY
    payload = str(runner_id).encode('utf-8')
    return hmac.new(secret.encode('utf-8') if isinstance(secret, str) else secret, payload, hashlib.sha256).hexdigest()


def _paypal_verify_runner_signature(runner_id, signature):
    """Verify an HMAC signature for a runner_id. Returns True if valid."""
    expected = _paypal_sign_runner_id(runner_id)
    return hmac.compare_digest(signature, expected)


def _create_paypal_order(request, runner_obj, race_obj):
    """Create a PayPal order via the REST API and return (approve_url, PayPalOrder) or raise."""
    from .paypal_client import get_paypal_client
    from paypalserversdk.models.order_request import OrderRequest
    from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
    from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest
    from paypalserversdk.models.amount_with_breakdown import AmountWithBreakdown
    from paypalserversdk.models.order_application_context import OrderApplicationContext
    from paypalserversdk.models.order_application_context_shipping_preference import OrderApplicationContextShippingPreference
    from paypalserversdk.models.order_application_context_landing_page import OrderApplicationContextLandingPage

    entry_fee = Decimal(str(race_obj.Entry_fee or 0))
    return_url = request.build_absolute_uri(reverse('tracker:paypal-return'))
    cancel_url = request.build_absolute_uri(reverse('tracker:paypal-cancel'))

    client = get_paypal_client()
    order_request = OrderRequest(
        intent=CheckoutPaymentIntent.CAPTURE,
        purchase_units=[
            PurchaseUnitRequest(
                amount=AmountWithBreakdown(
                    currency_code='USD',
                    value=f'{entry_fee:.2f}',
                ),
                description=f"Race entry: {race_obj.name}"[:127],
                custom_id=str(runner_obj.id),
            ),
        ],
        application_context=OrderApplicationContext(
            return_url=return_url,
            cancel_url=cancel_url,
            shipping_preference=OrderApplicationContextShippingPreference.NO_SHIPPING,
            landing_page=OrderApplicationContextLandingPage.LOGIN,
            brand_name='Simple5K',
        ),
    )

    response = client.orders.create_order({'body': order_request})
    order_data = response.body
    order_id = order_data.id

    approve_url = None
    for link in order_data.links:
        if link.rel == 'approve':
            approve_url = link.href
            break

    if not approve_url:
        raise RuntimeError(f"PayPal order {order_id} has no approve link")

    paypal_order = PayPalOrder.objects.create(
        order_id=order_id,
        runner=runner_obj,
        amount=entry_fee,
        currency='USD',
        status='CREATED',
    )

    return approve_url, paypal_order


def _capture_paypal_order(order_id):
    """Capture a PayPal order and return (capture_result_dict, error_string).
    On success: (result_dict, None). On failure: (None, error_message)."""
    from .paypal_client import get_paypal_client

    client = get_paypal_client()
    response = client.orders.capture_order({'id': order_id, 'prefer': 'return=representation'})
    result = response.body

    if result.status != 'COMPLETED':
        return None, f"Order status is {result.status}, not COMPLETED"

    capture = None
    if result.purchase_units:
        payments = result.purchase_units[0].payments
        if payments and payments.captures:
            capture = payments.captures[0]

    if not capture:
        return None, "No capture found in order response"

    payer_email = ''
    if result.payer and result.payer.email_address:
        payer_email = result.payer.email_address

    return {
        'capture_id': capture.id,
        'amount': Decimal(capture.amount.value),
        'currency': capture.amount.currency_code,
        'payer_email': payer_email,
        'status': result.status,
    }, None


def _pay_link_for_runner(runner):
    """Build the pay-later URL for a runner, or None if site_base_url is not set."""
    site_settings = SiteSettings.get_settings()
    base = (site_settings.site_base_url or '').strip().rstrip('/')
    if not base:
        return None
    signature = _paypal_sign_runner_id(runner.id)
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
            runner.send_signup_confirmation = True
            runner.save(update_fields=['send_signup_confirmation'])
            site_settings = SiteSettings.get_settings()
            entry_fee = float(selected_race.Entry_fee or 0)
            paypal_configured = bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET)
            if site_settings.paypal_enabled and paypal_configured and entry_fee > 0:
                try:
                    approve_url, _ = _create_paypal_order(request, runner, selected_race)
                    return redirect(approve_url)
                except Exception:
                    logger.exception("PayPal order creation failed for runner pk=%s", runner.pk)
            send_signup_confirmation_email(runner)
            return redirect(reverse('tracker:signup-success', args=[selected_race.id]))
    else:
        form = SignupForm()
    current_races = race.objects.filter(status='signup_open', archived=False).order_by('date', 'scheduled_time')
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
    """Shown after user approves payment on PayPal. Captures the order server-side,
    verifies the amount, and marks the runner as paid only if capture succeeds."""
    token = request.GET.get('token', '').strip()
    context = {'paid': False, 'error': None}

    if not token:
        context['error'] = 'No payment token received from PayPal.'
        return render(request, 'tracker/paypal_return.html', context)

    paypal_order = PayPalOrder.objects.filter(order_id=token).first()
    if not paypal_order:
        context['error'] = 'Payment record not found. Please contact the race organiser.'
        return render(request, 'tracker/paypal_return.html', context)

    runner = paypal_order.runner

    # If already captured (e.g. user refreshes the return page), skip re-capture
    if paypal_order.status == 'COMPLETED' and runner.paid:
        context['paid'] = True
        return render(request, 'tracker/paypal_return.html', context)

    try:
        result, error = _capture_paypal_order(token)
    except Exception:
        logger.exception("PayPal capture failed for order %s", token)
        context['error'] = 'We could not confirm your payment with PayPal. Please contact the race organiser.'
        return render(request, 'tracker/paypal_return.html', context)

    if error:
        logger.warning("PayPal capture error for order %s: %s", token, error)
        context['error'] = 'Payment could not be completed. Please try again or contact the race organiser.'
        return render(request, 'tracker/paypal_return.html', context)

    # Verify amount meets entry fee
    expected_fee = Decimal(str(runner.race.Entry_fee or 0))
    if expected_fee > 0 and result['amount'] < expected_fee:
        logger.warning(
            "PayPal underpayment: order=%s got %s expected %s",
            token, result['amount'], expected_fee,
        )
        context['error'] = 'Payment amount does not match the entry fee. Please contact the race organiser.'
        return render(request, 'tracker/paypal_return.html', context)

    # Update records
    paypal_order.status = 'COMPLETED'
    paypal_order.capture_id = result['capture_id']
    paypal_order.payer_email = result.get('payer_email', '')
    paypal_order.captured_at = timezone.now()
    paypal_order.save()

    runner.paid = True
    runner.save(update_fields=['paid'])

    if runner.send_signup_confirmation and not runner.signup_confirmation_sent:
        send_signup_confirmation_email(runner)

    context['paid'] = True
    logger.info("PayPal payment captured: order=%s capture=%s runner=%s amount=%s",
                token, result['capture_id'], runner.pk, result['amount'])
    return render(request, 'tracker/paypal_return.html', context)


def paypal_cancel(request):
    """Shown when user cancels PayPal payment. Runner remains registered but unpaid.
    Looks up the runner via the PayPal order token and sends signup confirmation with pay-later link.
    """
    if request.GET.get('sent') == '1':
        return render(request, 'tracker/paypal_cancel.html', {'sent': True})

    runner = None
    token = request.GET.get('token', '').strip()
    if token:
        paypal_order = PayPalOrder.objects.filter(order_id=token).first()
        if paypal_order:
            if paypal_order.status == 'CREATED':
                paypal_order.status = 'CANCELLED'
                paypal_order.save(update_fields=['status'])
            runner = paypal_order.runner

    if runner is not None:
        if runner.send_signup_confirmation and not runner.signup_confirmation_sent:
            send_signup_confirmation_email(runner)
            return redirect(reverse('tracker:paypal-cancel') + '?sent=1')

    return render(request, 'tracker/paypal_cancel.html', {'sent': False})


def pay_entry(request, runner_id, signature):
    """
    Pay-later page: valid link from signup confirmation email. Verifies runner_id + signature
    then creates a PayPal order and redirects to PayPal for payment.
    """
    if not _paypal_verify_runner_signature(runner_id, signature):
        raise Http404("Invalid or expired pay link.")
    try:
        runner_obj = runners.objects.get(pk=runner_id)
    except runners.DoesNotExist:
        raise Http404("Runner not found.")
    if runner_obj.paid:
        return redirect(reverse('tracker:signup-success', args=[runner_obj.race_id]))
    site_settings = SiteSettings.get_settings()
    race_obj = runner_obj.race
    entry_fee = float(race_obj.Entry_fee or 0)
    paypal_configured = settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET
    if not site_settings.paypal_enabled or not paypal_configured or entry_fee <= 0:
        return redirect(reverse('tracker:signup-success', args=[race_obj.id]))
    try:
        approve_url, _ = _create_paypal_order(request, runner_obj, race_obj)
        return redirect(approve_url)
    except Exception:
        logger.exception("PayPal order creation failed for pay_entry runner pk=%s", runner_obj.pk)
        return redirect(reverse('tracker:signup-success', args=[race_obj.id]))


def race_countdown(request):
    """Get countdown for all upcoming races along with active race information"""
    # Get races that haven't started yet (status is signup_open or signup_closed), exclude archived
    upcoming_races = race.objects.filter(status__in=['signup_open', 'signup_closed'], archived=False).order_by('date', 'scheduled_time')
    # Check for an active race (exclude archived)
    active_race = race.objects.filter(status='in_progress', archived=False).first()
    active_race_data = None

    if active_race:
        active_race_data = {
            'id': active_race.id,
            'name': active_race.name,
        }
    # Calculate remaining time for each race
    race_data = []
    for r in upcoming_races:
        # Combine date and scheduled_time; skip if no scheduled time
        if r.scheduled_time is None:
            remaining = {'days': 0, 'hours': 0, 'minutes': 0, 'seconds': 0}
        else:
            start_time = datetime.combine(r.date, r.scheduled_time)
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
