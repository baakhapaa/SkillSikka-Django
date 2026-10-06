"""Email verification for instructor signup, independent of password reset."""
from datetime import timedelta
import secrets

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.utils import timezone

from .models import InstructorSignupOTP

OTP_EXPIRY_SECONDS = 600
OTP_COOLDOWN_SECONDS = 60
OTP_MAX_ATTEMPTS = 5


def issue_signup_otp(user):
    """Caller holds a transaction and, for existing users, a user row lock."""
    otp = f'{secrets.randbelow(10000):04d}'
    InstructorSignupOTP.objects.filter(user=user, is_used=False).update(is_used=True)
    InstructorSignupOTP.objects.create(
        user=user, otp_hash=make_password(otp),
        expires_at=timezone.now() + timedelta(seconds=OTP_EXPIRY_SECONDS),
    )
    send_mail(
        'SkillSikka Instructor Signup OTP',
        f'Your SkillSikka signup OTP is {otp}. This OTP expires in 10 minutes.',
        settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False,
    )
