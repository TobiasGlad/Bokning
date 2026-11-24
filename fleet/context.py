from django.conf import settings
from .oauth import microsoft_ready

def navigation(request):
    return {'microsoft_ready': microsoft_ready(),
            'google_ready': bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
            'page_name': request.resolver_match.url_name if request.resolver_match else ''}
