from datetime import timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .models import Booking, Resource, Maintenance, Audit
from .calendars import CalendarClient, CalendarError, CalendarConflict


def validate_slot(resource, start, end, exclude=None):
    if not resource.active:
        raise ValidationError('Resursen är inte bokningsbar just nu.')
    if start >= end:
        raise ValidationError('Sluttiden måste vara efter starttiden.')
    if start < timezone.now():
        raise ValidationError('Starttiden måste ligga i framtiden.')
    if end - start > timedelta(hours=resource.max_hours):
        raise ValidationError(f'Du kan boka högst {resource.max_hours} timmar åt gången.')
    if end > timezone.now() + timedelta(days=resource.advance_days):
        raise ValidationError(f'Du kan boka högst {resource.advance_days} dagar framåt.')
    margin = timedelta(minutes=resource.buffer_minutes)
    overlapping = Booking.objects.filter(resource=resource, status__in=Booking.BLOCKING,
                                          start__lt=end + margin, end__gt=start - margin)
    if exclude:
        overlapping = overlapping.exclude(pk=exclude)
    if overlapping.exists():
        raise ValidationError('Tiden är redan bokad eller ligger inom marginalen till en annan bokning.')
    if Maintenance.objects.filter(resource=resource, start__lt=end + margin, end__gt=start - margin).exists():
        raise ValidationError('Resursen är blockerad för service under den valda tiden.')


def create_booking(resource, user, start, end, purpose, notes=''):
    # IMMEDIATE SQLite transactions serialize writers, including the first booking.
    with transaction.atomic():
        Resource.objects.filter(pk=resource.pk).update(lock_version=F('lock_version') + 1)
        resource = Resource.objects.select_for_update().get(pk=resource.pk)
        validate_slot(resource, start, end)
        booking = Booking.objects.create(resource=resource, user=user, start=start, end=end,
                    purpose=purpose, notes=notes, status='syncing' if resource.connection_id else 'confirmed')
        Audit.objects.create(actor=user, action='booking.created', description=f'Bokning {booking.pk} skapad')
    if resource.connection_id:
        sync_booking(booking.pk)
        booking.refresh_from_db()
    return booking


def sync_booking(pk):
    # Lock the record during sync; retries cannot send simultaneous provider writes.
    with transaction.atomic():
        booking = Booking.objects.select_for_update().select_related('resource__connection').get(pk=pk)
        if booking.status not in ['syncing', 'cancel_pending']:
            return booking
        client = CalendarClient(booking.resource.connection)
        try:
            if booking.status == 'cancel_pending':
                client.delete(booking)
                booking.status, booking.sync_error = 'cancelled', ''
            else:
                if not booking.remote_attempted:
                    margin = timedelta(minutes=booking.resource.buffer_minutes)
                    if client.busy(booking.resource, booking.start - margin, booking.end + margin):
                        raise CalendarConflict('Den externa kalendern är upptagen. Välj en annan tid.')
                    # Commit intent before network write in the separate transaction below.
                else:
                    booking.external_event_id = client.create(booking)
                    booking.status, booking.sync_error = 'confirmed', ''
            if booking.status != 'syncing' or booking.remote_attempted:
                booking.save(update_fields=['status', 'sync_error', 'external_event_id'])
                return booking
        except CalendarConflict as exc:
            booking.status, booking.sync_error = 'rejected', str(exc)
            booking.save(update_fields=['status', 'sync_error'])
            return booking
        except CalendarError as exc:
            booking.sync_error = str(exc)
            booking.save(update_fields=['sync_error'])
            return booking
        booking.remote_attempted = True
        booking.save(update_fields=['remote_attempted'])
    # Intent survives a process crash; stable event keys make the retry idempotent.
    return sync_booking(pk)


def cancel_booking(booking, actor):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if actor != booking.user and not actor.is_staff:
            raise ValidationError('Du kan bara avboka dina egna bokningar.')
        if booking.status not in ['confirmed', 'syncing', 'cancel_pending']:
            raise ValidationError('Bokningen kan inte avbokas.')
        if booking.start <= timezone.now() and not actor.is_staff:
            raise ValidationError('Bokningen har börjat. Använd återlämning eller kontakta administratören.')
        if booking.status == 'syncing' and booking.remote_attempted and not booking.external_event_id:
            raise ValidationError('Kalenderpostens status är okänd. Försök synkronisera före avbokning.')
        booking.status = 'cancel_pending' if booking.resource.connection_id else 'cancelled'
        booking.save(update_fields=['status'])
        Audit.objects.create(actor=actor, action='booking.cancelled', description=f'Avbokning {booking.pk}')
    if booking.status == 'cancel_pending':
        sync_booking(booking.pk)
        booking.refresh_from_db()
    return booking


def return_booking(booking, actor, mileage):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().select_related('resource').get(pk=booking.pk)
        resource = Resource.objects.select_for_update().get(pk=booking.resource_id)
        if actor != booking.user and not actor.is_staff:
            raise ValidationError('Du kan bara återlämna dina egna bokningar.')
        if booking.status != 'confirmed' or booking.start > timezone.now():
            raise ValidationError('Endast en påbörjad, bekräftad bokning kan återlämnas.')
        if mileage < resource.mileage:
            raise ValidationError('Mätarställningen får inte vara lägre än den nuvarande.')
        booking.status, booking.returned_at, booking.return_mileage = 'returned', timezone.now(), mileage
        booking.save(update_fields=['status', 'returned_at', 'return_mileage'])
        resource.mileage = mileage
        resource.save(update_fields=['mileage'])
        Audit.objects.create(actor=actor, action='booking.returned', description=f'Återlämning {booking.pk}')


def create_maintenance(resource, actor, start, end, reason):
    with transaction.atomic():
        Resource.objects.filter(pk=resource.pk).update(lock_version=F('lock_version') + 1)
        if start >= end:
            raise ValidationError('Sluttiden måste vara efter starttiden.')
        margin = timedelta(minutes=resource.buffer_minutes)
        if resource.bookings.filter(status__in=Booking.BLOCKING, start__lt=end + margin, end__gt=start - margin).exists():
            raise ValidationError('Perioden har bokningar. Flytta eller avboka dem innan serviceblockering skapas.')
        item = Maintenance.objects.create(resource=resource, start=start, end=end, reason=reason, created_by=actor)
        Audit.objects.create(actor=actor, action='maintenance.created', description=f'Serviceblockering {item.pk}')
        return item
