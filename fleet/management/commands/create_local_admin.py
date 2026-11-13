from getpass import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


class Command(BaseCommand):
    help = 'Skapa ett administratörskonto interaktivt. Lösenord skrivs aldrig till källkod.'

    def handle(self, *args, **options):
        email = input('E-post: ').strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError('Ogiltig e-postadress.') from exc
        if get_user_model().objects.filter(username=email).exists():
            raise CommandError('Kontot finns redan. Ingen ändring gjord.')
        first_name = input('Förnamn: ').strip()
        password = getpass('Lösenord: ')
        if password != getpass('Upprepa lösenord: '):
            raise CommandError('Lösenorden stämmer inte överens.')
        user = get_user_model()(username=email, email=email, first_name=first_name)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages)) from exc
        get_user_model().objects.create_superuser(username=email, email=email, password=password, first_name=first_name)
        self.stdout.write('Administratören skapad lokalt.')
