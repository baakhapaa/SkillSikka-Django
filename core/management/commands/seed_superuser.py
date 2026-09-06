from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from getpass import getpass

from core.models import Role, User


class Command(BaseCommand):
    help = 'Create or update the dashboard superuser in the users table.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument('--name', required=True)
        parser.add_argument('--password')

    def handle(self, *args, **options):
        email = options['email'].strip().lower()
        try:
            validate_email(email)
        except ValidationError as exc:
            raise CommandError('Provide a valid email address.') from exc

        password = options['password'] or getpass('Dashboard password: ')
        if len(password) < 8:
            raise CommandError('The password must be at least 8 characters long.')

        user = User.objects.filter(email=email).first()
        if user:
            user.name = options['name']
            user.role = Role.objects.get(name='super_admin')
            user.set_password(password)
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            user.onboarding_completed = True
            user.save()
            action = 'Updated'
        else:
            User.objects.create_superuser(
                email=email,
                password=password,
                name=options['name'],
            )
            action = 'Created'

        self.stdout.write(self.style.SUCCESS(f'{action} dashboard superuser {email}.'))
