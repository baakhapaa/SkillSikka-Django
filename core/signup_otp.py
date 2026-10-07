"""Shared student/instructor signup email verification, separate from password reset."""
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
# A 4-digit code allows 5 guesses per code; capping codes per day keeps the
# total guesses an attacker gets small.
OTP_MAX_ISSUES_PER_DAY = 10


def issue_signup_otp(user):
    """Caller holds a transaction and, for existing users, a user row lock."""
    otp = f'{secrets.randbelow(10000):04d}'
    InstructorSignupOTP.objects.filter(user=user, is_used=False).update(is_used=True)
    InstructorSignupOTP.objects.create(
        user=user, otp_hash=make_password(otp),
        expires_at=timezone.now() + timedelta(seconds=OTP_EXPIRY_SECONDS),
    )
    send_mail(
        f'SkillSikka {user.role.name.title()} Signup OTP',
        f'Your SkillSikka signup OTP is {otp}. This OTP expires in 10 minutes.',
        settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False,
    )
