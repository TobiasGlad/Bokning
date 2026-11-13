import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F
from django.utils import timezone


class CalendarConnection(models.Model):
    PROVIDERS = [('microsoft', 'Microsoft 365 / Outlook'), ('google', 'Google Kalender')]
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    name = models.CharField('Namn', max_length=160)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    encrypted_token = models.TextField(editable=False)
    active = models.BooleanField(default=True)
    last_checked = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=250, blank=True)

    def __str__(self):
        return self.name


class Resource(models.Model):
    KINDS = [('car', 'Bil'), ('van', 'Minibuss'), ('equipment', 'Utrustning'), ('other', 'Annan resurs')]
    FUELS = [('electric', 'El'), ('hybrid', 'Hybrid'), ('petrol', 'Bensin'), ('diesel', 'Diesel'), ('other', 'Annat')]
    name = models.CharField('Namn', max_length=120)
    kind = models.CharField('Resurstyp', max_length=20, choices=KINDS, default='car')
    registration = models.CharField('Registreringsnummer', max_length=20, blank=True)
    description = models.TextField('Beskrivning', blank=True)
    image = models.ImageField('Bild', upload_to='vehicles/%Y/%m/', blank=True)
    location = models.CharField('Hämtningsplats', max_length=160, blank=True)
    key_instructions = models.TextField('Nycklar och hämtning', blank=True)
    seats = models.PositiveSmallIntegerField('Antal platser', default=5)
    fuel = models.CharField('Drivmedel', choices=FUELS, max_length=15, default='electric')
    gearbox = models.CharField('Växellåda', max_length=15, choices=[('auto', 'Automat'), ('manual', 'Manuell')], default='auto')
    range_km = models.PositiveIntegerField('Räckvidd (km)', null=True, blank=True)
    mileage = models.PositiveIntegerField('Mätarställning (km)', default=0)
    buffer_minutes = models.PositiveSmallIntegerField('Marginal mellan bokningar (min)', default=15)
    max_hours = models.PositiveSmallIntegerField('Max bokningstid (timmar)', default=72)
    advance_days = models.PositiveSmallIntegerField('Bokningshorisont (dagar)', default=90)
    active = models.BooleanField('Bokningsbar', default=True)
    connection = models.ForeignKey(CalendarConnection, null=True, blank=True, on_delete=models.PROTECT, verbose_name='Kalenderanslutning')
    calendar_id = models.CharField('Kalender-ID', max_length=500, blank=True)
    mailbox = models.EmailField('Microsoft resursbrevlåda (valfritt)', blank=True)
    lock_version = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['connection', 'calendar_id', 'mailbox'],
                       condition=Q(connection__isnull=False), name='unique_external_calendar')]

    def clean(self):
        if self.connection_id and not self.calendar_id:
            raise ValidationError({'calendar_id': 'Ange kalender-ID (default för resursbrevlådans standardkalender). '})
        if self.calendar_id and not self.connection_id:
            raise ValidationError({'connection': 'Välj en kalenderanslutning.'})
        if self.connection_id and self.mailbox and self.connection.provider != 'microsoft':
            raise ValidationError({'mailbox': 'Resursbrevlåda används bara med Microsoft.'})
        if not self.max_hours or not self.advance_days:
            raise ValidationError('Bokningstid och bokningshorisont måste vara större än noll.')

    def __str__(self):
        return self.name


class Booking(models.Model):
    STATES = [('confirmed', 'Bekräftad'), ('syncing', 'Väntar på kalender'), ('cancel_pending', 'Avbokning väntar'),
              ('cancelled', 'Avbokad'), ('returned', 'Återlämnad'), ('rejected', 'Kalenderkonflikt')]
    BLOCKING = ['confirmed', 'syncing', 'cancel_pending', 'returned']
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name='bookings')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='bookings')
    start = models.DateTimeField('Från')
    end = models.DateTimeField('Till')
    purpose = models.CharField('Ändamål / destination', max_length=240)
    notes = models.TextField('Anteckning', blank=True)
    status = models.CharField(max_length=20, choices=STATES, default='confirmed')
    external_event_id = models.CharField(max_length=500, blank=True)
    remote_attempted = models.BooleanField(default=False)
    sync_error = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    return_mileage = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['start']
        constraints = [models.CheckConstraint(condition=Q(end__gt=F('start')), name='booking_end_after_start')]
        indexes = [models.Index(fields=['resource', 'start', 'end', 'status'])]

    def __str__(self):
        return f'{self.resource} · {timezone.localtime(self.start):%Y-%m-%d %H:%M}'


class Maintenance(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name='maintenance')
    start = models.DateTimeField('Från')
    end = models.DateTimeField('Till')
    reason = models.CharField('Orsak', max_length=240)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ['start']
        constraints = [models.CheckConstraint(condition=Q(end__gt=F('start')), name='maintenance_end_after_start')]


class Issue(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name='issues')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    description = models.TextField('Beskriv felet')
    resolved = models.BooleanField('Åtgärdad', default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class Identity(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    provider = models.CharField(max_length=20)
    subject = models.CharField(max_length=255)
    issuer = models.CharField(max_length=255)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['provider', 'issuer', 'subject'], name='unique_sso_identity')]


class Audit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=100)
    description = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(default=timezone.now)
