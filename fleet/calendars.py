"""Provider adapters. Only fixed provider hosts are requested; secrets stay encrypted."""
import json
from datetime import timedelta
from urllib.parse import quote, urlparse
import requests
from cryptography.fernet import Fernet
from django.conf import settings
from django.utils import timezone
from .models import CalendarConnection


class CalendarError(Exception):
    pass


class CalendarConflict(CalendarError):
    pass


def encrypt_token(token):
    return Fernet(settings.TOKEN_ENCRYPTION_KEY.encode()).encrypt(json.dumps(dict(token)).encode()).decode()


def decrypt_token(value):
    return json.loads(Fernet(settings.TOKEN_ENCRYPTION_KEY.encode()).decrypt(value.encode()))


def request_json(method, url, **kwargs):
    try:
        response = requests.request(method, url, timeout=(5, 20), allow_redirects=False, **kwargs)
        if response.status_code >= 400 or response.status_code < 200 or response.status_code >= 300:
            raise CalendarError('Kalendertjänsten kunde inte slutföra begäran. Kontrollera behörigheter och anslutning.')
        return response.json() if response.content else {}
    except (requests.RequestException, ValueError) as exc:
        raise CalendarError('Kalendertjänsten svarar inte. Bokningen är inte bekräftad.') from exc


def access_token(connection):
    if not connection.active:
        raise CalendarError('Kalenderanslutningen är avstängd.')
    try:
        token = decrypt_token(connection.encrypted_token)
    except Exception as exc:
        raise CalendarError('Kalenderanslutningen behöver anslutas på nytt.') from exc
    if token.get('expires_at', 0) > timezone.now().timestamp() + 60:
        return token['access_token']
    if not token.get('refresh_token'):
        raise CalendarError('Kalenderanslutningen behöver anslutas på nytt.')
    if connection.provider == 'google':
        url = 'https://oauth2.googleapis.com/token'
        client_id, secret = settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
    else:
        url = f'https://login.microsoftonline.com/{quote(settings.MICROSOFT_TENANT, safe="")}/oauth2/v2.0/token'
        client_id, secret = settings.MICROSOFT_CLIENT_ID, settings.MICROSOFT_CLIENT_SECRET
    refreshed = request_json('POST', url, data={'grant_type': 'refresh_token', 'refresh_token': token['refresh_token'],
                            'client_id': client_id, 'client_secret': secret})
    if not refreshed.get('access_token'):
        raise CalendarError('Kalenderanslutningen behöver anslutas på nytt.')
    token.update(refreshed)
    token['expires_at'] = timezone.now().timestamp() + int(refreshed.get('expires_in', 3600))
    CalendarConnection.objects.filter(pk=connection.pk).update(encrypted_token=encrypt_token(token))
    return token['access_token']


class CalendarClient:
    def __init__(self, connection):
        self.connection = connection
        self.google = connection.provider == 'google'
        self.base = 'https://www.googleapis.com/calendar/v3' if self.google else 'https://graph.microsoft.com/v1.0'

    def call(self, method, path, **kwargs):
        url = path if path.startswith('https://') else self.base + path
        if urlparse(url).netloc != urlparse(self.base).netloc:
            raise CalendarError('Ogiltig adress i kalendersvar.')
        headers = {'Authorization': 'Bearer ' + access_token(self.connection)}
        if not self.google:
            headers['Prefer'] = 'outlook.timezone="UTC"'
        return request_json(method, url, headers=headers, **kwargs)

    def pages(self, path, params=None):
        for _ in range(100):
            data = self.call('GET', path, params=params)
            yield from data.get('items' if self.google else 'value', [])
            if self.google and data.get('nextPageToken'):
                params = {**(params or {}), 'pageToken': data['nextPageToken']}
            elif not self.google and data.get('@odata.nextLink'):
                path, params = data['@odata.nextLink'], None
            else:
                return
        raise CalendarError('Kalendern innehåller för många poster för en säker kontroll.')

    def discover(self):
        if self.google:
            return [{'id': e['id'], 'name': e.get('summary', e['id']), 'mailbox': '', 'kind': 'car'}
                    for e in self.pages('/users/me/calendarList', {'minAccessRole': 'writer'})]
        items = [{'id': e['id'], 'name': e.get('name', e['id']), 'mailbox': '', 'kind': 'car'}
                 for e in self.pages('/me/calendars') if e.get('canEdit')]
        return items

    def discover_rooms(self):
        # Graph Places exposes rooms. Equipment mailboxes can instead be entered by email.
        return [{'id': 'default', 'name': e.get('displayName', e['emailAddress']),
                 'mailbox': e['emailAddress'], 'kind': 'other'}
                for e in self.pages('/places/microsoft.graph.room') if e.get('emailAddress')]

    def path(self, resource):
        calendar = quote(resource.calendar_id, safe='')
        if self.google:
            return f'/calendars/{calendar}/events'
        if resource.mailbox:
            base = '/users/' + quote(resource.mailbox, safe='')
            return base + ('/calendar/events' if resource.calendar_id == 'default' else f'/calendars/{calendar}/events')
        return f'/me/calendars/{calendar}/events'

    def busy(self, resource, start, end, exclude_id=''):
        # Use expanded events so that retries can exclude this application's own event.
        path = self.path(resource)
        if self.google:
            params = {'timeMin': start.isoformat(), 'timeMax': end.isoformat(), 'singleEvents': 'true', 'maxResults': 2500}
        else:
            path = path.removesuffix('/events') + '/calendarView'
            params = {'startDateTime': start.isoformat(), 'endDateTime': end.isoformat(), '$top': 1000}
        intervals = []
        for event in self.pages(path, params):
            if event.get('id') == exclude_id or event.get('status') == 'cancelled' or event.get('isCancelled'):
                continue
            if event.get('transparency') == 'transparent' or event.get('showAs') in ['free', 'workingElsewhere']:
                continue
            from datetime import datetime
            from zoneinfo import ZoneInfo
            def moment(value):
                raw = value.get('dateTime', value.get('date'))
                if not raw:
                    raise CalendarError('En kalenderpost saknar giltig tid.')
                parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                if timezone.is_naive(parsed):
                    zone = value.get('timeZone', 'UTC' if not self.google else 'Europe/Stockholm')
                    try:
                        parsed = parsed.replace(tzinfo=ZoneInfo(zone))
                    except (KeyError, ValueError) as exc:
                        raise CalendarError('Kalenderpostens tidszon kunde inte tolkas.') from exc
                return parsed
            a, b = moment(event['start']), moment(event['end'])
            if a < end and b > start:
                intervals.append((a, b))
        CalendarConnection.objects.filter(pk=self.connection.pk).update(last_checked=timezone.now(), last_error='')
        return intervals

    def create(self, booking):
        # Stable provider keys prevent duplicates after a timeout.
        start, end = booking.start, booking.end + timedelta(minutes=booking.resource.buffer_minutes)
        summary = f'Bokning · {booking.resource.name}'
        if self.google:
            body = {'id': booking.id.hex, 'summary': summary, 'start': {'dateTime': start.isoformat()},
                    'end': {'dateTime': end.isoformat()}, 'description': 'Bokad via Bokning.'}
        else:
            body = {'subject': summary, 'transactionId': str(booking.id), 'showAs': 'busy',
                    'start': {'dateTime': start.astimezone(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'UTC'},
                    'end': {'dateTime': end.astimezone(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'UTC'}}
        path = self.path(booking.resource)
        if self.google and booking.remote_attempted:
            # An earlier write may have succeeded. Resolve first; don't blindly duplicate.
            try:
                return self.call('GET', path + '/' + booking.id.hex)['id']
            except CalendarError:
                pass
        return self.call('POST', path, json=body)['id']

    def delete(self, booking):
        event_id = booking.external_event_id
        if not event_id and self.google and booking.remote_attempted:
            event_id = booking.id.hex
        if not event_id:
            if booking.remote_attempted:
                raise CalendarError('Kalenderpostens status är okänd. Slutför synkronisering före avbokning.')
            return
        # DELETE is idempotent, including an already removed event.
        url = self.base + self.path(booking.resource) + '/' + quote(event_id, safe='')
        try:
            response = requests.delete(url, headers={'Authorization': 'Bearer ' + access_token(self.connection)},
                                       timeout=(5, 20), allow_redirects=False)
            if response.status_code not in [200, 202, 204, 404, 410]:
                raise CalendarError('Kalenderposten kunde inte tas bort.')
        except requests.RequestException as exc:
            raise CalendarError('Avbokningen väntar på kalendertjänsten.') from exc
