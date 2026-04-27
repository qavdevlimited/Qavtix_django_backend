from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from rest_framework.exceptions import ValidationError
from django.contrib.auth import get_user_model

User = get_user_model()

class MySocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        user = sociallogin.user

        # If no email yet, let populate_user handle it later
        email = (
            user.email
            or sociallogin.account.extra_data.get("email")
        )
        if not email:
            return

        existing_user = User.objects.filter(email__iexact=email).first()
        if not existing_user:
            return  # new user → allow

        two_fa = getattr(existing_user, "two_factor_auth", None)
        if not two_fa:
            return

        provider = sociallogin.account.provider
        is_enabled = getattr(two_fa, provider, True)

        if not is_enabled:
            raise ValidationError(
                f"{provider.capitalize()} login is not active in your account."
            )

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        email = sociallogin.account.extra_data.get('email') or data.get('email')
        if not email:
            raise ValidationError("Social did not provide an email. Please register manually.")

        user.email = email

        if not user.username:
            base = (user.first_name or 'user') + (user.last_name or '')
            user.username = base[:30]

        return user


    def save_user(self, request, sociallogin, form=None):
        """
        Prevent overwriting password for existing users.
        """
        user = sociallogin.user
        email = user.email

        existing_user = User.objects.filter(email=email).first()

        if existing_user:
            sociallogin.connect(request, existing_user)
            return existing_user

        # New user → safe to proceed normally
        user.set_unusable_password()
        return super().save_user(request, sociallogin, form)