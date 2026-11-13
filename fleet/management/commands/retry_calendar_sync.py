from django.core.management.base import BaseCommand
from fleet.models import Booking
from fleet.services import sync_booking


class Command(BaseCommand):
    help = 'Försök slutföra väntande kalenderbokningar och avbokningar.'

    def handle(self, *args, **options):
        count = 0
        for pk in Booking.objects.filter(status__in=['syncing', 'cancel_pending']).values_list('pk', flat=True):
            sync_booking(pk)
            count += 1
        self.stdout.write(f'{count} väntande bokningar kontrollerade. Se administrationen för kvarvarande fel.')
