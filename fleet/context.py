from django.conf import settings

def navigation(request):
    return {'microsoft_ready': bool(settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET and settings.MICROSOFT_TENANT),
            'google_ready': bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
            'page_name': request.resolver_match.url_name if request.resolver_match else ''}
