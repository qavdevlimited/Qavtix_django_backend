from rest_framework.exceptions import ValidationError

class SocialLoginRestrictionMixin:
    """
    Blocks login if user has disabled a social auth method.
    Only affects LOGIN, not registration.
    """

    provider_name = None  # "google" or "facebook"

    def enforce_2fa_restriction(self, user):
        two_fa = getattr(user, "two_factor_auth", None)

        # If user has no settings yet → allow (new user)
        if not two_fa:
            return

        is_enabled = getattr(two_fa, self.provider_name, True)

        if not is_enabled:
            raise ValidationError(
                f"{self.provider_name.capitalize()} login is not active in your account."
            )