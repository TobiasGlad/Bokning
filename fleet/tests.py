import io
import tempfile
from datetime import timedelta
from unittest.mock import patch, Mock
from PIL import Image
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import Resource, Booking, Maintenance, CalendarConnection, Issue, Identity
from .forms import ResourceForm
from .services import create_booking, cancel_booking, return_booking, create_maintenance, sync_booking
from .calendars import CalendarError, encrypt_token, decrypt_token, CalendarClient


class BookingRules(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('driver@example.invalid', password='Test-driver-4839')
        self.other = get_user_model().objects.create_user('other@example.invalid', password='Test-other-4839')
        self.resource = Resource.objects.create(name='Testbil', buffer_minutes=15)
        self.start = timezone.now() + timedelta(days=1)
        self.end = self.start + timedelta(hours=2)

    def book(self, **kwargs):
        return create_booking(**{'resource': self.resource, 'user': self.user, 'start': self.start,
                                 'end': self.end, 'purpose': 'Testresa', **kwargs})

    def test_direct_booking_and_overlap(self):
        item = self.book()
        self.assertEqual(item.status, 'confirmed')
        for start, end in [(self.start,self.end), (self.start-timedelta(hours=1),self.end+timedelta(hours=1)),
                           (self.end,self.end+timedelta(hours=1)), (self.start-timedelta(hours=1),self.start)]:
            with self.assertRaises(ValidationError):
                self.book(start=start, end=end)
        self.assertEqual(Booking.objects.count(), 1)

    def test_exact_buffer_boundary_is_allowed(self):
        self.book()
        self.book(start=self.end+timedelta(minutes=15), end=self.end+timedelta(hours=2))
        self.assertEqual(Booking.objects.count(),2)

    def test_default_resource_accepts_adjacent_and_separate_bookings_same_day(self):
        resource = Resource.objects.create(name='Flera resor samma dag')
        self.assertEqual(resource.buffer_minutes, 0)
        morning = timezone.localtime(self.start).replace(hour=9, minute=0, second=0, microsecond=0)
        for hour in [9, 10, 13]:
            start = morning.replace(hour=hour)
            self.book(resource=resource, start=start, end=start + timedelta(hours=1))
        self.assertEqual(resource.bookings.count(), 3)
        for start, end in [(morning, morning + timedelta(hours=1)),
                           (morning + timedelta(minutes=30), morning + timedelta(hours=1, minutes=30)),
                           (morning - timedelta(minutes=30), morning + timedelta(hours=3))]:
            with self.assertRaises(ValidationError):
                self.book(resource=resource, start=start, end=end)
        self.assertEqual(resource.bookings.count(), 3)

    def test_cancel_frees_slot_and_enforces_owner(self):
        item = self.book()
        with self.assertRaises(ValidationError):
            cancel_booking(item, self.other)
        cancel_booking(item, self.user)
        self.book()

    def test_invalid_time_horizon_duration_inactive(self):
        cases = [{'start': self.end, 'end': self.start}, {'start': timezone.now()-timedelta(hours=1)},
                 {'end': self.start+timedelta(hours=73)}, {'start': self.start+timedelta(days=100), 'end': self.end+timedelta(days=100)}]
        for kwargs in cases:
            with self.assertRaises(ValidationError): self.book(**kwargs)
        self.resource.active=False
        self.resource.save()
        with self.assertRaises(ValidationError): self.book()

    def test_service_blocks_booking_and_cannot_overwrite_existing(self):
        block = create_maintenance(self.resource, self.user, self.start, self.end, 'Service')
        with self.assertRaises(ValidationError): self.book()
        block.delete()
        self.book()
        with self.assertRaises(ValidationError): create_maintenance(self.resource, self.user, self.start, self.end, 'Service')

    def test_return_mileage_and_repeated_return(self):
        item=self.book()
        with self.assertRaises(ValidationError): return_booking(item,self.user,10)
        Booking.objects.filter(pk=item.pk).update(start=timezone.now()-timedelta(hours=1))
        return_booking(item,self.user,120)
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.mileage,120)
        with self.assertRaises(ValidationError): return_booking(item,self.user,121)

    @patch('fleet.services.CalendarClient')
    def test_external_busy_rejects_without_write(self, adapter):
        connection=CalendarConnection.objects.create(provider='google',name='Test',owner=self.user,encrypted_token='test')
        self.resource.connection=connection; self.resource.calendar_id='test'; self.resource.save()
        adapter.return_value.busy.return_value=[(self.start,self.end)]
        item=self.book()
        self.assertEqual(item.status,'rejected')
        adapter.return_value.create.assert_not_called()

    @patch('fleet.services.CalendarClient')
    def test_sync_timeout_retains_reservation_and_retry_is_idempotent(self, adapter):
        connection=CalendarConnection.objects.create(provider='google',name='Test',owner=self.user,encrypted_token='test')
        self.resource.connection=connection; self.resource.calendar_id='test'; self.resource.save()
        adapter.return_value.busy.return_value=[]
        adapter.return_value.create.side_effect=CalendarError('Timeout')
        item=self.book()
        self.assertEqual(item.status,'syncing')
        self.assertTrue(item.remote_attempted)
        with self.assertRaises(ValidationError): self.book()
        adapter.return_value.create.side_effect=None
        adapter.return_value.create.return_value='event-123'
        sync_booking(item.pk)
        item.refresh_from_db()
        self.assertEqual(item.status,'confirmed')
        self.assertEqual(item.external_event_id,'event-123')
        calls=adapter.return_value.create.call_count
        sync_booking(item.pk)
        self.assertEqual(adapter.return_value.create.call_count,calls)

    @patch('fleet.services.CalendarClient')
    def test_failed_cancel_stays_blocking(self, adapter):
        connection=CalendarConnection.objects.create(provider='microsoft',name='Test',owner=self.user,encrypted_token='test')
        self.resource.connection=connection; self.resource.calendar_id='test'; self.resource.save()
        adapter.return_value.busy.return_value=[]
        adapter.return_value.create.return_value='event'
        item=self.book()
        adapter.return_value.delete.side_effect=CalendarError('Timeout')
        result=cancel_booking(item,self.user)
        self.assertEqual(result.status,'cancel_pending')
        with self.assertRaises(ValidationError): self.book()
        adapter.return_value.delete.side_effect=None
        sync_booking(item.pk)
        item.refresh_from_db()
        self.assertEqual(item.status,'cancelled')


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False)
class ViewsAndSecurity(TestCase):
    def setUp(self):
        self.admin=get_user_model().objects.create_superuser('admin@example.invalid','admin@example.invalid','Test-admin-4839')
        self.user=get_user_model().objects.create_user('user@example.invalid','user@example.invalid','Test-user-4839')
        self.resource=Resource.objects.create(name='Testbil', registration='ABC123')
        self.start=timezone.now()+timedelta(days=1)
        self.item=create_booking(self.resource,self.admin,self.start,self.start+timedelta(hours=2),'Privat ändamål')

    def test_anonymous_pages_and_protected_routes(self):
        self.assertEqual(self.client.get('/bokning/login/').status_code,200)
        for path in ['/bokning/','/bokning/anvandare/','/bokning/hantera/','/bokning/resurser/1/bild/']:
            self.assertEqual(self.client.get(path).status_code,302)
        self.assertEqual(self.client.get('/bokning/logout/').status_code,405)
        self.assertEqual(self.client.get('/bokning/oauth/google/start/').status_code,405)

    def test_all_admin_pages_render(self):
        self.client.force_login(self.admin)
        paths=['/bokning/','/bokning/kalender/','/bokning/bokningar/','/bokning/hantera/', '/bokning/anvandare/',
               '/bokning/anvandare/ny/','/bokning/konto/','/bokning/integrationer/','/bokning/boka/',
               '/bokning/resurser/ny/',f'/bokning/resurser/{self.resource.pk}/', f'/bokning/resurser/{self.resource.pk}/redigera/',
               '/bokning/hantera/service/ny/',f'/bokning/bokningar/{self.item.pk}/', f'/bokning/anvandare/{self.user.pk}/losenord/']
        for path in paths:
            with self.subTest(path=path): self.assertEqual(self.client.get(path).status_code,200)

    def test_staff_permissions_and_private_booking(self):
        self.client.force_login(self.user)
        for path in ['/bokning/anvandare/','/bokning/hantera/','/bokning/integrationer/','/bokning/rapporter/bokningar.csv','/bokning/resurser/ny/']:
            self.assertEqual(self.client.get(path).status_code,403)
        for path in [f'/bokning/bokningar/{self.item.pk}/',f'/bokning/bokningar/{self.item.pk}/kalender.ics']:
            self.assertEqual(self.client.get(path).status_code,404)
        response=self.client.get('/bokning/kalender/')
        self.assertNotContains(response,'Privat ändamål')

    def test_csrf_required_for_booking_and_logout(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/bokning/boka/',{}).status_code,403)
        self.assertEqual(client.post('/bokning/logout/').status_code,403)

    def test_login_throttling(self):
        for _ in range(5): self.client.post('/bokning/login/',{'email':self.user.email,'password':'wrong'})
        response=self.client.post('/bokning/login/',{'email':self.user.email,'password':'Test-user-4839'})
        self.assertContains(response,'För många försök')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_disable_self_rejected(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('user_toggle',args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_pwa_scope_and_no_cache(self):
        manifest=self.client.get('/bokning/manifest.webmanifest').json()
        self.assertEqual(manifest['scope'],'/bokning/')
        self.assertEqual(manifest['start_url'],'/bokning/')
        response=self.client.get('/bokning/sw.js')
        self.assertEqual(response['Service-Worker-Allowed'],'/bokning/')
        self.assertIn('no-store',self.client.get('/bokning/login/')['Cache-Control'])
        self.assertEqual(self.client.get('/bokning/offline/').status_code,200)

    def test_ics_and_csv_export(self):
        self.client.force_login(self.admin)
        response=self.client.get(reverse('booking_ics',args=[self.item.pk]))
        self.assertContains(response,'BEGIN:VCALENDAR')
        self.assertContains(response,'DTSTART:')
        Booking.objects.filter(pk=self.item.pk).update(purpose='=HYPERLINK("bad")')
        response=self.client.get('/bokning/rapporter/bokningar.csv')
        self.assertContains(response,"'=HYPERLINK")

    def test_resource_calendar_change_blocked_with_future_booking(self):
        self.client.force_login(self.admin)
        data={'name':'Testbil','kind':'car','registration':'ABC123','seats':5,'fuel':'electric','gearbox':'auto','mileage':0,
              'buffer_minutes':60,'max_hours':72,'advance_days':90,'active':'on'}
        response=self.client.post(reverse('resource_edit',args=[self.resource.pk]), data)
        self.assertContains(response,'Kalenderkoppling och marginal')
        self.resource.refresh_from_db()
        self.assertEqual(self.resource.buffer_minutes,0)

    def test_calendar_offers_another_time_and_adjacent_booking_can_be_submitted(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('calendar'), {'date': timezone.localdate(self.item.start).isoformat()})
        self.assertContains(response, 'Boka en annan tid')
        start = timezone.localtime(self.item.end).replace(second=0, microsecond=0) + timedelta(minutes=1)
        # The business-rule test also covers exact equal end/start boundaries.
        data = {'resource': self.resource.pk, 'start': start.strftime('%Y-%m-%dT%H:%M'),
                'end': (start + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'), 'purpose': 'Andra resan'}
        response = self.client.post(reverse('book'), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.resource.bookings.count(), 2)

    def test_sso_state_required(self):
        response=self.client.get('/bokning/oauth/google/callback/?state=forged&code=bad')
        self.assertEqual(response.status_code,403)

    @override_settings(GOOGLE_CLIENT_ID='test', GOOGLE_CLIENT_SECRET='test', SSO_ALLOWED_DOMAINS=['example.invalid'])
    @patch('fleet.oauth.client')
    def test_sso_never_auto_links_existing_email(self, remote):
        session=self.client.session
        import time
        session['oauth_intent_test']={'provider':'google','mode':'login','user':None,'time':time.time()}
        session.save()
        remote.return_value.authorize_access_token.return_value={'userinfo':{'sub':'attacker','iss':'https://accounts.google.com',
                                                                'email':self.admin.email,'email_verified':True}}
        self.client.get('/bokning/oauth/google/callback/?state=test&code=valid')
        self.assertNotIn('_auth_user_id',self.client.session)
        self.assertFalse(Identity.objects.exists())

    @override_settings(GOOGLE_CLIENT_ID='test', GOOGLE_CLIENT_SECRET='test', SSO_ALLOWED_DOMAINS=['example.invalid'])
    @patch('fleet.oauth.client')
    def test_sso_new_user_and_explicit_link(self, remote):
        import time
        session=self.client.session
        session['oauth_intent_test']={'provider':'google','mode':'login','user':None,'time':time.time()};session.save()
        remote.return_value.authorize_access_token.return_value={'userinfo':{'sub':'new','iss':'https://accounts.google.com',
            'email':'new@example.invalid','email_verified':True,'given_name':'New'}}
        self.client.get('/bokning/oauth/google/callback/?state=test&code=valid')
        self.assertIn('_auth_user_id',self.client.session)
        self.assertFalse(get_user_model().objects.get(email='new@example.invalid').is_staff)

    def test_photo_reencoding_and_protection(self):
        image=Image.new('RGB',(40,20),'green');content=io.BytesIO();image.save(content,'PNG')
        upload=SimpleUploadedFile('photo.png',content.getvalue(),content_type='image/png')
        data={'name':'Photo','kind':'car','seats':5,'fuel':'electric','gearbox':'auto','mileage':0,
              'buffer_minutes':15,'max_hours':72,'advance_days':90,'active':'on'}
        with tempfile.TemporaryDirectory() as folder, override_settings(MEDIA_ROOT=folder):
            form=ResourceForm(data,{'image':upload})
            self.assertTrue(form.is_valid(),form.errors)
            resource=form.save()
            self.assertTrue(resource.image.name.endswith('.jpg'))
            self.assertEqual(self.client.get(reverse('resource_photo',args=[resource.pk])).status_code,302)
            self.client.force_login(self.user)
            response=self.client.get(reverse('resource_photo',args=[resource.pk]))
            self.assertEqual(response.status_code,200)
            self.assertTrue(b''.join(response.streaming_content).startswith(b'\xff\xd8'))


class CalendarAdapters(TestCase):
    @override_settings(TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_tokens_encrypted(self):
        token={'access_token':'secret-value','refresh_token':'refresh-value'}
        encrypted=encrypt_token(token)
        self.assertNotIn('secret-value',encrypted)
        self.assertEqual(decrypt_token(encrypted),token)

    def test_untrusted_pagination_host_rejected(self):
        connection=CalendarConnection(provider='google')
        with self.assertRaises(CalendarError): CalendarClient(connection).call('GET','https://evil.invalid/steal')

    def test_microsoft_resource_mailbox_path(self):
        connection=CalendarConnection(provider='microsoft')
        resource=Resource(calendar_id='default',mailbox='car@example.invalid')
        self.assertEqual(CalendarClient(connection).path(resource),'/users/car%40example.invalid/calendar/events')

    @patch('fleet.calendars.CalendarClient.call')
    def test_recurring_instances_free_events_and_utc(self, call):
        connection=CalendarConnection(provider='microsoft')
        # No database connection is needed for parsing, only the final health timestamp update.
        now=timezone.now().replace(microsecond=0)
        start=now.isoformat();end=(now+timedelta(hours=1)).isoformat()
        call.return_value={'value':[{'id':'1','start':{'dateTime':start},'end':{'dateTime':end}},
                                   {'id':'2','showAs':'free','start':{'dateTime':start},'end':{'dateTime':end}}]}
        result=CalendarClient(connection).busy(Resource(calendar_id='test'),now-timedelta(minutes=1),now+timedelta(hours=2))
        self.assertEqual(len(result),1)
        self.assertIn('calendarView',call.call_args.args[1])


from django.test import TransactionTestCase
from django.db import connection, connections, close_old_connections
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


class ConcurrentBooking(TransactionTestCase):
    def test_only_one_simultaneous_booking_wins(self):
        if 'memory' in connection.settings_dict['NAME']:
            self.skipTest('Ange TEST_DATABASE till en tillfällig fil för samtidighetstestet.')
        user=get_user_model().objects.create_user('concurrent@example.invalid')
        resource=Resource.objects.create(name='Samtidighetstest')
        start=timezone.now()+timedelta(days=1)
        barrier=Barrier(2)
        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                create_booking(resource,user,start,start+timedelta(hours=1),'Samtidig bokning')
                return 'confirmed'
            except ValidationError:
                return 'conflict'
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertCountEqual(results,['confirmed','conflict'])
        self.assertEqual(Booking.objects.count(),1)


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False)
class UnitSelection(TestCase):
    def setUp(self):
        from .models import Unit
        self.unit = Unit.objects.create(name='Testenhet')
        self.inactive = Unit.objects.create(name='Avslutad enhet', active=False)
        self.user = get_user_model().objects.create_user('unit-user@example.invalid')
        self.admin = get_user_model().objects.create_superuser('unit-admin@example.invalid', 'unit-admin@example.invalid', 'Admin-test-9483')
        self.resource = Resource.objects.create(name='Enhetstestbil')
        self.start = timezone.now() + timedelta(days=1)
        self.end = self.start + timedelta(hours=1)

    def data(self, unit):
        return {'resource': self.resource.pk, 'unit': unit,
            'start': timezone.localtime(self.start).strftime('%Y-%m-%dT%H:%M'),
            'end': timezone.localtime(self.end).strftime('%Y-%m-%dT%H:%M'), 'purpose': 'Enhetstest'}

    def test_booking_saves_selected_unit_and_shows_details(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('book'), self.data(self.unit.pk))
        self.assertEqual(response.status_code, 302)
        booking = Booking.objects.get()
        self.assertEqual(booking.unit_id, self.unit.pk)
        self.assertContains(self.client.get(reverse('booking', args=[booking.pk])), 'Testenhet')
        self.assertContains(self.client.get(reverse('bookings')), 'Testenhet')

    def test_inactive_and_forged_unit_cannot_be_selected(self):
        from .forms import BookingForm
        self.assertNotIn(self.inactive, BookingForm().fields['unit'].queryset)
        for value in [self.inactive.pk, 999999]:
            form = BookingForm(self.data(value))
            self.assertFalse(form.is_valid())
            self.assertIn('unit', form.errors)
        with self.assertRaises(ValidationError):
            create_booking(self.resource, self.user, self.start, self.end, 'Test', unit=self.inactive)
        self.assertFalse(Booking.objects.exists())

    def test_deactivation_keeps_existing_bookings(self):
        from django.db.models.deletion import ProtectedError
        booking = create_booking(self.resource, self.user, self.start, self.end, 'Test', unit=self.unit)
        self.unit.active = False
        self.unit.save()
        booking.refresh_from_db()
        self.assertEqual(booking.unit.name, 'Testenhet')
        with self.assertRaises(ProtectedError):
            self.unit.delete()

    def test_units_are_managed_only_by_administrators(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('units')).status_code, 403)
        self.assertEqual(self.client.post(reverse('unit_create'), {'name': 'Ny enhet', 'active': 'on'}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('units')).status_code, 200)
        response = self.client.post(reverse('unit_create'), {'name': 'Ny enhet', 'active': 'on'})
        self.assertRedirects(response, reverse('units'))
        response = self.client.post(reverse('unit_edit', args=[self.unit.pk]), {'name': self.unit.name})
        self.assertRedirects(response, reverse('units'))
        self.unit.refresh_from_db()
        self.assertFalse(self.unit.active)

    def test_csv_includes_unit_and_booking_without_unit_is_supported(self):
        create_booking(self.resource, self.user, self.start, self.end, 'Test', unit=self.unit)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('export')), 'Testenhet')
        form_data = self.data('')
        from .forms import BookingForm
        self.assertTrue(BookingForm(form_data).is_valid())


@override_settings(SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False, SECURE_SSL_REDIRECT=False)
class ResourceColors(TestCase):
    def test_automatic_colors_spread_across_palette_and_stay_stable(self):
        first = Resource.objects.create(name='Bil A')
        second = Resource.objects.create(name='Bil B')
        self.assertNotEqual(first.booking_color, second.booking_color)
        color = first.booking_color
        first.name = 'Bil A uppdaterad'
        first.save()
        first.refresh_from_db()
        self.assertEqual(first.booking_color, color)
        self.assertEqual(first.color_class, 'resource-color-' + color)

    def test_admin_can_choose_color_and_arbitrary_color_is_rejected(self):
        from .forms import ResourceForm
        data = {'name':'Bil','booking_color':'rose','kind':'car','seats':5,'fuel':'electric','gearbox':'auto',
                'mileage':0,'buffer_minutes':0,'max_hours':72,'advance_days':90,'active':'on'}
        form = ResourceForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().booking_color, 'rose')
        data['booking_color'] = 'untrusted-css'
        form = ResourceForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn('booking_color', form.errors)

    def test_calendar_and_booking_list_use_the_same_resource_color(self):
        user = get_user_model().objects.create_user('color-test@example.invalid')
        resource = Resource.objects.create(name='Lila testbil', booking_color='purple')
        start = timezone.now() + timedelta(days=1)
        booking = create_booking(resource, user, start, start + timedelta(hours=1), 'Testresa')
        self.client.force_login(user)
        response = self.client.get(reverse('calendar'), {'date': timezone.localdate(start).isoformat()})
        self.assertContains(response, 'calendar-event confirmed resource-color-purple')
        self.assertContains(response, 'resource-legend-item resource-color-purple')
        self.assertContains(self.client.get(reverse('bookings')), 'booking-row resource-color-purple')
        self.assertContains(self.client.get(reverse('booking', args=[booking.pk])), 'page-heading resource-color-purple')
