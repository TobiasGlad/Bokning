import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, time
from functools import wraps
from pathlib import Path
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, F, Sum
from django.http import HttpResponse, HttpResponseForbidden, FileResponse, JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET
from .models import Resource, Booking, Maintenance, Issue, CalendarConnection, Audit, LoginAttempt
from .forms import ResourceForm, BookingForm, UserForm, IssueForm, MaintenanceForm, ReturnForm
from .services import create_booking, cancel_booking, return_booking, create_maintenance, sync_booking
from .calendars import CalendarClient, CalendarError


def staff_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden('Administratör krävs.')
        return view(request, *args, **kwargs)
    return wrapped


def errors(request, exc):
    messages.error(request, ' '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc))


def sign_in(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        key = hashlib.sha256((request.META.get('REMOTE_ADDR', '') + ':' + email).encode()).hexdigest()
        cutoff = timezone.now() - timedelta(minutes=15)
        with transaction.atomic():
            attempt, _ = LoginAttempt.objects.get_or_create(key=key)
            if attempt.updated_at < cutoff:
                attempt.failures = 0
            blocked = attempt.failures >= 5
            if not blocked:
                attempt.failures += 1
                attempt.updated_at = timezone.now()
                attempt.save()
        if blocked:
            messages.error(request, 'För många försök. Vänta 15 minuter och försök igen.')
        else:
            user = authenticate(request, username=email, password=request.POST.get('password', ''))
            if user:
                LoginAttempt.objects.filter(key=key).delete()
                login(request, user)
                Audit.objects.create(actor=user, action='login.password', description='Inloggning med lösenord')
                return redirect('dashboard')
            messages.error(request, 'E-post eller lösenord stämmer inte.')
    return render(request, 'fleet/login.html')


@require_POST
def sign_out(request):
    logout(request)
    return redirect('login')


@login_required
def dashboard(request):
    now = timezone.now()
    today = timezone.localdate()
    resources = Resource.objects.filter(active=True).select_related('connection')
    q = request.GET.get('q', '').strip()
    if q:
        resources = resources.filter(Q(name__icontains=q) | Q(registration__icontains=q) | Q(location__icontains=q))
    kind = request.GET.get('kind', '')
    if kind:
        resources = resources.filter(kind=kind)
    fuel = request.GET.get('fuel', '')
    if fuel:
        resources = resources.filter(fuel=fuel)
    start_raw, end_raw = request.GET.get('start', ''), request.GET.get('end', '')
    slot_form = BookingForm({'start': start_raw, 'end': end_raw, 'purpose': 'Sök', 'resource': resources.first().pk if resources.exists() else ''})
    searching_time = bool(start_raw and end_raw)
    available_ids = None
    slot_start, slot_end = None, None
    if searching_time:
        slot_form.is_valid()
        slot_start, slot_end = slot_form.cleaned_data.get('start'), slot_form.cleaned_data.get('end')
        if not slot_start or not slot_end or slot_start >= slot_end:
            messages.error(request, 'Ange ett giltigt tidsintervall.')
            searching_time = False
    cards = []
    for resource in resources:
        margin = timedelta(minutes=resource.buffer_minutes)
        current = resource.bookings.filter(status__in=Booking.BLOCKING, start__lte=now, end__gt=now - margin).first()
        service = resource.maintenance.filter(start__lte=now, end__gt=now).first()
        next_booking = resource.bookings.filter(status__in=Booking.BLOCKING, start__gt=now).first()
        availability = 'Ledig nu' if not current and not service else ('Service' if service else 'Bokad nu')
        available = not current and not service
        if searching_time:
            from .services import validate_slot
            try:
                validate_slot(resource, slot_start, slot_end)
                if resource.connection_id and CalendarClient(resource.connection).busy(resource, slot_start - margin, slot_end + margin):
                    continue
            except ValidationError:
                continue
            except CalendarError:
                availability, available = 'Kalenderkontroll behövs', False
            else:
                availability, available = 'Ledig vald tid', True
        elif resource.connection_id:
            # Don't imply external availability from local records alone.
            availability = 'Kalender kontrolleras vid bokning' if available else availability
        cards.append({'resource': resource, 'available': available, 'label': availability, 'next': next_booking})
    upcoming = request.user.bookings.filter(end__gte=now, status__in=['confirmed', 'syncing', 'cancel_pending']).select_related('resource')[:3]
    return render(request, 'fleet/dashboard.html', {'cards': cards, 'upcoming': upcoming, 'q': q, 'kind': kind, 'fuel': fuel,
        'start_value': start_raw, 'end_value': end_raw, 'total_resources': Resource.objects.filter(active=True).count(),
        'my_count': request.user.bookings.filter(end__gte=now, status__in=['confirmed', 'syncing']).count(),
        'today_count': Booking.objects.filter(start__date=today, status='confirmed').count(),
        'issues_count': Issue.objects.filter(resolved=False).count() if request.user.is_staff else 0})


@login_required
def resource_detail(request, pk):
    resource = get_object_or_404(Resource.objects.select_related('connection'), pk=pk)
    now = timezone.now()
    return render(request, 'fleet/resource.html', {'resource': resource,
        'bookings': resource.bookings.filter(status__in=Booking.BLOCKING, end__gte=now)[:12],
        'maintenance': resource.maintenance.filter(end__gte=now)[:5], 'issue_form': IssueForm(),
        'issues': resource.issues.filter(resolved=False).select_related('user') if request.user.is_staff else []})


@login_required
def resource_photo(request, pk):
    resource = get_object_or_404(Resource, pk=pk)
    if not resource.image:
        raise Http404
    try:
        return FileResponse(resource.image.open('rb'), content_type='image/jpeg')
    except FileNotFoundError:
        raise Http404


@staff_required
def resource_edit(request, pk=None):
    item = get_object_or_404(Resource, pk=pk) if pk else None
    form = ResourceForm(request.POST or None, request.FILES or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            if item:
                Resource.objects.filter(pk=item.pk).update(lock_version=F('lock_version') + 1)
                previous = Resource.objects.get(pk=item.pk)
                changed = any(field in form.changed_data for field in ['connection', 'calendar_id', 'mailbox', 'buffer_minutes'])
                if changed and previous.bookings.filter(status__in=['confirmed', 'syncing', 'cancel_pending'], end__gt=timezone.now()).exists():
                    form.add_error(None, 'Kalenderkoppling och marginal kan ändras när resursens framtida bokningar är avslutade.')
                else:
                    item = form.save()
            else:
                item = form.save()
            if not form.errors:
                Audit.objects.create(actor=request.user, action='resource.saved', description=f'Resurs {item.pk} sparad')
                messages.success(request, 'Resursen är sparad.')
                return redirect('resource', pk=item.pk)
    return render(request, 'fleet/form.html', {'form': form, 'title': 'Redigera resurs' if pk else 'Lägg till resurs',
                  'eyebrow': 'FORDON & RESURSER', 'submit': 'Spara resurs', 'multipart': True})


@login_required
def book(request):
    initial = {}
    if request.GET.get('resource'):
        initial['resource'] = request.GET['resource']
    now = timezone.localtime().replace(second=0, microsecond=0) + timedelta(hours=1)
    initial.update(start=request.GET.get('start') or now, end=request.GET.get('end') or now + timedelta(hours=2))
    form = BookingForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            booking = create_booking(user=request.user, **form.cleaned_data)
            if booking.status == 'confirmed':
                messages.success(request, 'Din bokning är bekräftad.')
            elif booking.status == 'rejected':
                messages.error(request, booking.sync_error)
            else:
                messages.warning(request, 'Bokningen väntar på kalendern och är ännu inte bekräftad.')
            return redirect('booking', pk=booking.pk)
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, 'fleet/form.html', {'form': form, 'title': 'Boka en resurs', 'eyebrow': 'EN RESA I TAGET',
        'intro': 'Välj bil och tid. Bokningen bekräftas direkt när bilen och kalendern är lediga.', 'submit': 'Bekräfta bokning'})


@login_required
def bookings(request):
    items = Booking.objects.select_related('resource', 'user')
    team = request.GET.get('view') == 'team' and request.user.is_staff
    if not team:
        items = items.filter(user=request.user)
    past = request.GET.get('period') == 'past'
    if past:
        items = items.filter(Q(end__lt=timezone.now()) | Q(status__in=['cancelled', 'rejected', 'returned'])).order_by('-start')
    else:
        items = items.filter(end__gte=timezone.now(), status__in=['confirmed', 'syncing', 'cancel_pending'])
    from django.core.paginator import Paginator
    return render(request, 'fleet/bookings.html', {'items': Paginator(items, 25).get_page(request.GET.get('page')), 'past': past, 'team': team})


def own_booking(request, pk):
    booking = get_object_or_404(Booking.objects.select_related('resource', 'user'), pk=pk)
    if booking.user_id != request.user.pk and not request.user.is_staff:
        raise Http404
    return booking


@login_required
def booking_detail(request, pk):
    booking = own_booking(request, pk)
    now = timezone.now()
    return render(request, 'fleet/booking.html', {'booking': booking,
        'can_cancel': booking.status in ['confirmed', 'syncing'] and (booking.start > now or request.user.is_staff),
        'can_return': booking.status == 'confirmed' and booking.start <= now,
        'return_form': ReturnForm(initial={'mileage': booking.resource.mileage})})


@login_required
@require_POST
def booking_action(request, pk, action):
    booking = own_booking(request, pk)
    try:
        if action == 'cancel':
            result = cancel_booking(booking, request.user)
            messages.success(request, 'Bokningen är avbokad.' if result.status == 'cancelled' else 'Avbokningen väntar på kalendern. Tiden hålls tills kalendern svarat.')
        elif action == 'retry':
            result = sync_booking(booking.pk)
            messages.info(request, f'Kalenderstatus: {result.get_status_display()}')
        elif action == 'return':
            form = ReturnForm(request.POST)
            if form.is_valid():
                return_booking(booking, request.user, form.cleaned_data['mileage'])
                messages.success(request, 'Bilen är återlämnad. Tack!')
            else:
                messages.error(request, 'Ange en giltig mätarställning.')
        else:
            raise Http404
    except (ValidationError, CalendarError) as exc:
        errors(request, exc)
    return redirect('booking', pk=pk)


@login_required
@require_POST
def issue_create(request, pk):
    resource = get_object_or_404(Resource, pk=pk)
    form = IssueForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.resource, item.user = resource, request.user
        item.save()
        Audit.objects.create(actor=request.user, action='issue.created', description=f'Felanmälan {item.pk}')
        messages.success(request, 'Felanmälan är skickad till administratören.')
    else:
        messages.error(request, 'Beskriv felet innan du skickar.')
    return redirect('resource', pk=pk)


@staff_required
@require_POST
def issue_resolve(request, pk):
    item = get_object_or_404(Issue, pk=pk)
    item.resolved = True
    item.save(update_fields=['resolved'])
    Audit.objects.create(actor=request.user, action='issue.resolved', description=f'Felanmälan {item.pk} åtgärdad')
    messages.success(request, 'Felanmälan är markerad som åtgärdad.')
    return redirect('manage')


@login_required
def calendar_view(request):
    try:
        selected = datetime.strptime(request.GET.get('date', ''), '%Y-%m-%d').date()
    except ValueError:
        selected = timezone.localdate()
    start = timezone.make_aware(datetime.combine(selected, time.min))
    end = start + timedelta(days=7)
    days = [selected + timedelta(days=i) for i in range(7)]
    resources = Resource.objects.filter(active=True).select_related('connection')
    rows = []
    for resource in resources:
        events = list(resource.bookings.filter(status__in=Booking.BLOCKING, start__lt=end, end__gt=start))
        blocks = list(resource.maintenance.filter(start__lt=end, end__gt=start))
        cells = []
        for day in days:
            a = timezone.make_aware(datetime.combine(day, time.min))
            b = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))
            cells.append({'day': day, 'bookings': [e for e in events if e.start < b and e.end > a],
                          'blocks': [e for e in blocks if e.start < b and e.end > a]})
        rows.append({'resource': resource, 'cells': cells})
    return render(request, 'fleet/calendar.html', {'rows': rows, 'days': days, 'selected': selected,
        'previous': selected - timedelta(days=7), 'next': selected + timedelta(days=7)})


@staff_required
def manage(request):
    return render(request, 'fleet/manage.html', {'resources': Resource.objects.all(),
        'issues': Issue.objects.filter(resolved=False).select_related('resource', 'user'),
        'maintenance': Maintenance.objects.filter(end__gte=timezone.now()).select_related('resource'),
        'audit': Audit.objects.select_related('actor')[:20],
        'pending': Booking.objects.filter(status__in=['syncing', 'cancel_pending']).select_related('resource', 'user')})


@staff_required
def maintenance_create(request):
    form = MaintenanceForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            create_maintenance(actor=request.user, **form.cleaned_data)
            messages.success(request, 'Serviceperioden är blockerad lokalt.')
            return redirect('manage')
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request, 'fleet/form.html', {'form': form, 'title': 'Blockera för service', 'eyebrow': 'UNDERHÅLL',
        'intro': 'Serviceblockeringar hindrar bokningar här. Lägg även in service i den externa kalendern om bilen kan bokas där.', 'submit': 'Blockera tiden'})


@staff_required
@require_POST
def maintenance_delete(request, pk):
    get_object_or_404(Maintenance, pk=pk).delete()
    Audit.objects.create(actor=request.user, action='maintenance.deleted', description=f'Serviceblockering {pk} borttagen')
    messages.success(request, 'Serviceblockeringen är borttagen.')
    return redirect('manage')


@staff_required
def users(request):
    return render(request, 'fleet/users.html', {'users': get_user_model().objects.order_by('first_name', 'email')})


@staff_required
def user_create(request):
    form = UserForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        Audit.objects.create(actor=request.user, action='user.created', description=f'Användare {user.pk} skapad')
        messages.success(request, 'Användaren är skapad.')
        return redirect('users')
    return render(request, 'fleet/form.html', {'form': form, 'title': 'Skapa användare', 'eyebrow': 'BEHÖRIGHETER', 'submit': 'Skapa konto'})


@staff_required
@require_POST
def user_toggle(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk)
    if user.pk == request.user.pk or (user.is_superuser and not request.user.is_superuser):
        messages.error(request, 'Det här kontot kan du inte stänga av.')
    else:
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        Audit.objects.create(actor=request.user, action='user.toggled', description=f'Användare {user.pk}, aktiv: {user.is_active}')
    return redirect('users')


@staff_required
def user_password(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk)
    if user.is_superuser and not request.user.is_superuser:
        return HttpResponseForbidden()
    form = SetPasswordForm(user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        if user.pk == request.user.pk:
            update_session_auth_hash(request, user)
        Audit.objects.create(actor=request.user, action='user.password_reset', description=f'Lösenord bytt för användare {user.pk}')
        messages.success(request, 'Lösenordet är ändrat.')
        return redirect('users')
    return render(request, 'fleet/form.html', {'form': form, 'title': 'Byt användarens lösenord', 'eyebrow': 'BEHÖRIGHETER', 'submit': 'Spara lösenord'})


@login_required
def profile(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        update_session_auth_hash(request, request.user)
        messages.success(request, 'Ditt lösenord är ändrat.')
        return redirect('profile')
    return render(request, 'fleet/profile.html', {'form': form, 'identities': request.user.identity_set.all()})


@staff_required
def integrations(request):
    return render(request, 'fleet/integrations.html', {'connections': CalendarConnection.objects.all()})


@staff_required
def discover(request, pk):
    connection = get_object_or_404(CalendarConnection, pk=pk, active=True)
    items = []
    try:
        client = CalendarClient(connection)
        items = client.discover_rooms() if request.GET.get('type') == 'rooms' and connection.provider == 'microsoft' else client.discover()
    except CalendarError as exc:
        errors(request, exc)
    # Store only the validated provider-returned selection, never tokens, in the server session.
    request.session['calendar_choices'] = {'connection': connection.pk, 'items': items}
    return render(request, 'fleet/discover.html', {'connection': connection, 'items': items})


@staff_required
@require_POST
def import_resource(request, pk):
    data = request.session.get('calendar_choices', {})
    connection = get_object_or_404(CalendarConnection, pk=pk, active=True)
    try:
        index = int(request.POST.get('index', '-1'))
        if data.get('connection') != pk or index < 0:
            raise ValueError
        item = data['items'][index]
    except (ValueError, IndexError, KeyError):
        return HttpResponseForbidden('Hämta kalenderlistan igen.')
    resource, created = Resource.objects.get_or_create(connection=connection, calendar_id=item['id'], mailbox=item.get('mailbox', ''),
        defaults={'name': item['name'][:120], 'kind': item.get('kind', 'car')})
    if created:
        Audit.objects.create(actor=request.user, action='resource.imported', description=f'Resurs {resource.pk} importerad')
    messages.success(request, 'Resursen är importerad. Komplettera med bild, registreringsnummer och bokningsregler.')
    return redirect('resource_edit', pk=resource.pk)


@staff_required
@require_POST
def connection_toggle(request, pk):
    connection = get_object_or_404(CalendarConnection, pk=pk)
    connection.active = not connection.active
    connection.save(update_fields=['active'])
    Audit.objects.create(actor=request.user, action='calendar.toggled', description=f'Kalenderanslutning {pk}, aktiv: {connection.active}')
    messages.info(request, 'Anslutningens status är ändrad. Kopplade resurser kan bara bokas när kalenderkontrollen fungerar.')
    return redirect('integrations')


def ics_escape(value):
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '').replace(';', '\\;').replace(',', '\\,')


@login_required
def booking_ics(request, pk):
    booking = own_booking(request, pk)
    if booking.status not in ['confirmed', 'returned']:
        return HttpResponse('Endast bekräftade bokningar kan exporteras.', status=400)
    from datetime import timezone as dt_timezone
    stamp = lambda t: t.astimezone(dt_timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Bokning//SV', 'BEGIN:VEVENT',
        f'UID:{booking.pk}@bokning', 'DTSTAMP:' + stamp(booking.created_at),
        'DTSTART:' + stamp(booking.start), 'DTEND:' + stamp(booking.end),
        'SUMMARY:' + ics_escape(booking.resource.name), 'LOCATION:' + ics_escape(booking.resource.location),
        'DESCRIPTION:' + ics_escape(booking.purpose), 'END:VEVENT', 'END:VCALENDAR']
    folded = []
    for line in lines:
        chunk = ''
        for char in line:
            if len((chunk + char).encode()) > 73:
                folded.append(chunk)
                chunk = ' '
            chunk += char
        folded.append(chunk)
    response = HttpResponse('\r\n'.join(folded) + '\r\n', content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="bokning.ics"'
    return response


@staff_required
def export(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="bokningar.csv"'
    response.write('\ufeff')
    writer = csv.writer(response, delimiter=';')
    writer.writerow(['Resurs', 'Regnr', 'Användare', 'Från', 'Till', 'Status', 'Ändamål', 'Återlämnad km'])
    def safe(value):
        text = str(value if value is not None else '')
        return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t')) else text
    for booking in Booking.objects.select_related('resource', 'user').iterator():
        writer.writerow([safe(x) for x in [booking.resource.name, booking.resource.registration, booking.user.email,
            timezone.localtime(booking.start).isoformat(), timezone.localtime(booking.end).isoformat(),
            booking.get_status_display(), booking.purpose, booking.return_mileage]])
    Audit.objects.create(actor=request.user, action='report.export', description='Bokningsrapport exporterad')
    return response


def manifest(request):
    return JsonResponse({'id': '/bokning/', 'name': 'Bokning · Bilpool', 'short_name': 'Bokning', 'lang': 'sv',
        'start_url': '/bokning/', 'scope': '/bokning/', 'display': 'standalone', 'background_color': '#f5f6f2',
        'theme_color': '#164c3c', 'description': 'Boka bilar och gemensamma resurser.',
        'icons': [{'src': f'/bokning/static/bokning/icon-{size}.png', 'sizes': f'{size}x{size}', 'type': 'image/png', 'purpose': 'any maskable'} for size in [192, 512]]},
        content_type='application/manifest+json')


def service_worker(request):
    response = HttpResponse((settings.BASE_DIR / 'static/bokning/sw.js').read_text(), content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/bokning/'
    return response


def offline(request):
    return render(request, 'fleet/offline.html')
