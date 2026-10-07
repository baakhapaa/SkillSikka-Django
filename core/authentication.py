from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.authentication import default_user_authentication_rule


def email_authentication_rule(user):
    return default_user_authentication_rule(user) and not (
        user.role.name in ('student', 'instructor') and not user.email_verified
    )


class EmailVerifiedJWTAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        if not email_authentication_rule(user):
            raise AuthenticationFailed('Verify your email before signing in.')
        return user
