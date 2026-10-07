from datetime import timedelta

from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import InstructorSignupOTP, User
from .signup_otp import (
    OTP_COOLDOWN_SECONDS, OTP_MAX_ATTEMPTS, OTP_MAX_ISSUES_PER_DAY, issue_signup_otp,
)


class SignupEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class SignupVerifySerializer(SignupEmailSerializer):
    otp = serializers.RegexField(r'\A[0-9]{4}\Z', trim_whitespace=False, write_only=True)


class VerifySignupOTPAPIView(APIView):
    role_name = None
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = SignupVerifySerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        invalid = {'detail': 'Invalid or expired OTP.'}
        with transaction.atomic():
            user = User.objects.select_for_update().filter(
                email__iexact=serializer.validated_data['email'].strip(),
                role__name=self.role_name, email_verified=False, is_active=True,
            ).first()
            if user is None:
                return Response(invalid, status=status.HTTP_400_BAD_REQUEST)
            record = InstructorSignupOTP.objects.filter(user=user, is_used=False).first()
            if record is None:
                return Response(invalid, status=status.HTTP_400_BAD_REQUEST)
            if record.expires_at <= timezone.now() or record.failed_attempts >= OTP_MAX_ATTEMPTS:
                record.is_used = True
                record.save(update_fields=['is_used'])
                return Response(invalid, status=status.HTTP_400_BAD_REQUEST)
            if not check_password(serializer.validated_data['otp'], record.otp_hash):
                record.failed_attempts += 1
                record.is_used = record.failed_attempts >= OTP_MAX_ATTEMPTS
                record.save(update_fields=['failed_attempts', 'is_used'])
                return Response(invalid, status=status.HTTP_400_BAD_REQUEST)
            record.is_used = True
            record.save(update_fields=['is_used'])
            user.email_verified = True
            user.save(update_fields=['email_verified', 'updated_at'])
            refresh = RefreshToken.for_user(user)
            return Response({
                'detail': 'Email verified successfully.',
                'user': {
                    'id': str(user.id), 'email': user.email, 'name': user.name,
                    'role': self.role_name, 'verification_status': user.verification_status,
                    'email_verified': True,
                },
                'tokens': {'refresh': str(refresh), 'access': str(refresh.access_token)},
            })


class ResendSignupOTPAPIView(APIView):
    role_name = None
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = SignupEmailSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            user = User.objects.select_for_update().filter(
                email__iexact=serializer.validated_data['email'].strip(),
                role__name=self.role_name, email_verified=False, is_active=True,
            ).first()
            if user is not None:
                now = timezone.now()
                latest = InstructorSignupOTP.objects.filter(user=user).first()
                issued_today = InstructorSignupOTP.objects.filter(
                    user=user, created_at__gte=now - timedelta(days=1),
                ).count()
                cooled_down = latest is None or (now - latest.created_at).total_seconds() >= OTP_COOLDOWN_SECONDS
                if cooled_down and issued_today < OTP_MAX_ISSUES_PER_DAY:
                    issue_signup_otp(user)
        # Same response for absent/verified/inactive accounts and cooldown suppression.
        return Response({
            'detail': 'If an eligible account exists and the resend cooldown has elapsed, a signup OTP has been sent.',
        })


class VerifyInstructorSignupOTPAPIView(VerifySignupOTPAPIView):
    role_name = 'instructor'


class VerifyStudentSignupOTPAPIView(VerifySignupOTPAPIView):
    role_name = 'student'


class ResendInstructorSignupOTPAPIView(ResendSignupOTPAPIView):
    role_name = 'instructor'


class ResendStudentSignupOTPAPIView(ResendSignupOTPAPIView):
    role_name = 'student'
