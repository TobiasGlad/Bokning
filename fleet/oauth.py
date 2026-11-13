import secrets
import time
from urllib.parse import quote
from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from .calendars import encrypt_token
from .models import Identity, CalendarConnection, Audit


def client(provider):
    oauth = OAuth()
    if provider == 'google' and settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        return oauth.register('google', client_id=settings.GOOGLE_CLIENT_ID, client_secret=settings.GOOGLE_CLIENT_SECRET,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256', 'timeout': 20})
    if provider == 'microsoft' and settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET and settings.MICROSOFT_TENANT:
        tenant = quote(settings.MICROSOFT_TENANT, safe='')
        return oauth.register('microsoft', client_id=settings.MICROSOFT_CLIENT_ID, client_secret=settings.MICROSOFT_CLIENT_SECRET,
            server_metadata_url=f'https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256', 'timeout': 20})
    return None


@require_POST
def start(request, provider):
    if provider not in ['google', 'microsoft']:
        raise Http404
    remote = client(provider)
    if remote is None:
        messages.error(request, 'Inloggningen är inte aktiverad ännu. Kontakta administratören.')
        return redirect('login')
    mode = request.POST.get('mode', 'login')
    if mode not in ['login', 'link', 'calendar']:
        return HttpResponseForbidden()
    if mode in ['link', 'calendar'] and not request.user.is_authenticated:
        return redirect('login')
    if mode == 'calendar' and not request.user.is_staff:
        return HttpResponseForbidden()
    state = secrets.token_urlsafe(32)
    request.session['oauth_intent_' + state] = {'mode': mode, 'user': request.user.pk, 'time': time.time(), 'provider': provider}
    kwargs = {'state': state, 'nonce': secrets.token_urlsafe(32)}
    if mode == 'calendar':
        kwargs['scope'] = ('openid email profile https://www.googleapis.com/auth/calendar' if provider == 'google'
                           else 'openid email profile offline_access User.Read Calendars.ReadWrite Calendars.ReadWrite.Shared Place.Read.All')
        kwargs['prompt'] = 'consent'
        if provider == 'google':
            kwargs['access_type'] = 'offline'
    try:
        return remote.authorize_redirect(request, settings.PUBLIC_ORIGIN + reverse('oauth_callback', args=[provider]), **kwargs)
    except Exception:
        messages.error(request, 'Det gick inte att kontakta inloggningstjänsten. Försök senare.')
        return redirect('integrations' if request.user.is_authenticated else 'login')


def callback(request, provider):
    state = request.GET.get('state', '')
    intent = request.session.pop('oauth_intent_' + state, None)
    if not intent or intent['provider'] != provider or time.time() - intent['time'] > 600:
        return HttpResponseForbidden('Inloggningsförsöket har löpt ut. Börja om.')
    if intent['mode'] in ['link', 'calendar'] and (not request.user.is_authenticated or request.user.pk != intent['user']):
        return HttpResponseForbidden()
    if intent['mode'] == 'calendar' and not request.user.is_staff:
        return HttpResponseForbidden()
    try:
        remote = client(provider)
        if remote is None:
            raise ValidationError('Inloggningen är avstängd.')
        token = remote.authorize_access_token(request)
        info = token.get('userinfo')
        # Authlib verifies signature, issuer, audience, expiration, state, nonce and PKCE.
        if not info or not info.get('sub') or not info.get('iss'):
            raise ValidationError('Identiteten kunde inte verifieras.')
        if provider == 'google' and not info.get('email_verified'):
            raise ValidationError('E-postadressen måste vara verifierad hos Google.')
        email = (info.get('email') or info.get('preferred_username') or '').strip().lower()
        validate_email(email)
        if intent['mode'] == 'calendar':
            name = f'{"Google" if provider == "google" else "Microsoft"} · {email}'
            # Reauthorization repairs existing resource links instead of orphaning them.
            connection = CalendarConnection.objects.filter(provider=provider, name=name, owner=request.user).first()
            if connection:
                connection.encrypted_token = encrypt_token(token)
                connection.active, connection.last_error = True, ''
                connection.save(update_fields=['encrypted_token', 'active', 'last_error'])
            else:
                CalendarConnection.objects.create(provider=provider, name=name, owner=request.user, encrypted_token=encrypt_token(token))
            Audit.objects.create(actor=request.user, action='calendar.connected', description='Kalenderanslutning skapad')
            messages.success(request, 'Kalendern är ansluten. Importera en resurs eller koppla kalendern till en befintlig bil.')
            return redirect('integrations')
        with transaction.atomic():
            identity = Identity.objects.filter(provider=provider, subject=info['sub'], issuer=info['iss']).select_related('user').first()
            if intent['mode'] == 'link':
                if identity and identity.user_id != request.user.pk:
                    raise ValidationError('Identiteten är redan kopplad till ett annat konto.')
                if not identity:
                    Identity.objects.create(user=request.user, provider=provider, subject=info['sub'], issuer=info['iss'])
                messages.success(request, 'Inloggningen är kopplad till ditt konto.')
                return redirect('profile')
            if identity:
                user = identity.user
            else:
                if get_user_model().objects.filter(email__iexact=email).exists():
                    raise ValidationError('Ett konto finns redan. Logga in med lösenord och koppla inloggningen under Mitt konto.')
                domain = email.rsplit('@', 1)[-1]
                if not settings.SSO_ALLOWED_DOMAINS or domain not in settings.SSO_ALLOWED_DOMAINS:
                    raise ValidationError('Kontot har inte bjudits in. Kontakta administratören.')
                user = get_user_model().objects.create_user(username=email, email=email,
                    first_name=info.get('given_name', ''), last_name=info.get('family_name', ''), password=None)
                Identity.objects.create(user=user, provider=provider, subject=info['sub'], issuer=info['iss'])
            if not user.is_active:
                raise ValidationError('Kontot är avstängt.')
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        Audit.objects.create(actor=user, action='login.sso', description=f'Inloggning via {provider}')
        return redirect('dashboard')
    except ValidationError as exc:
        messages.error(request, ' '.join(exc.messages))
    except Exception:
        # Provider responses may contain tokens; never log the raw exception.
        messages.error(request, 'Inloggningen kunde inte slutföras. Kontrollera appregistrering och behörigheter.')
    return redirect('profile' if request.user.is_authenticated else 'login')
