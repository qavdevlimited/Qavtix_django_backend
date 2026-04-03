import random
import string

from django.contrib.auth import authenticate
from django.utils import timezone

from ..models import AdminOTP
from ..task import send_otp_email


class AdminAuthService:

    @staticmethod
    def verify_credentials(email: str, password: str):
        """
        Validates email + password.
        Returns the user if valid and is an admin, raises AuthError otherwise.
        """
        user = authenticate(username=email, password=password)

        if user is None:
            raise AuthError("Invalid email or password.", 401)

        if not user.is_active:
            raise AuthError("This account has been deactivated.", 403)

        try:
            _ = user.admin_profile
        except Exception:
            # Intentionally vague — don't reveal whether the account
            # exists but lacks admin privileges
            raise AuthError("No admin account found with these login details.", 401)

        return user

    @staticmethod
    def generate_and_send_otp(user) -> str:
        """
        Generates a 6-digit OTP, saves it, fires the email task async.
        Returns the temp_token string for the client to hold onto.
        """
        # Invalidate any previous unused OTPs for this user
        AdminOTP.objects.filter(user=user, is_used=False).update(is_used=True)

        otp    = _generate_otp()
        record = AdminOTP.objects.create(user=user, otp=otp)

        profile   = user.admin_profile
        full_name = profile.full_name if profile else user.email

        # Fire async — does not block the login response
        send_otp_email.delay(
            user_email=user.email,
            full_name=full_name,
            otp=otp,
        )

        return str(record.temp_token)

    @staticmethod
    def verify_otp(temp_token: str, otp: str):
        """
        Validates the OTP against the temp_token.
        Returns the user on success, raises AuthError on any failure.
        """
        try:
            record = AdminOTP.objects.select_related("user").get(
                temp_token=temp_token
            )
        except AdminOTP.DoesNotExist:
            raise AuthError("Invalid or expired session. Please log in again.", 400)

        if record.is_used:
            raise AuthError("This OTP has already been used.", 400)

        if timezone.now() > record.expires_at:
            raise AuthError("OTP has expired. Please log in again.", 400)

        if record.otp != otp:
            raise AuthError("Incorrect OTP.", 400)

        # Consume the OTP — cannot be reused
        record.is_used = True
        record.save(update_fields=["is_used"])

        return record.user


def _generate_otp(length=6) -> str:
    """Generates a numeric OTP of the given length."""
    return "".join(random.choices(string.digits, k=length))


class AuthError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)