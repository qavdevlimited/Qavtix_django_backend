from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from rest_framework.exceptions import ValidationError
from django.contrib.auth import get_user_model

User = get_user_model()

class MySocialAccountAdapter(DefaultSocialAccountAdapter):

    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)

        email = sociallogin.account.extra_data.get('email') or data.get('email')
        if not email:
            raise ValidationError("Facebook did not provide an email. Please register manually.")

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
            # 🔥 IMPORTANT: reuse existing user instead of creating new one
            sociallogin.connect(request, existing_user)
            return existing_user

        # New user → safe to proceed normally
        user.set_unusable_password()
        return super().save_user(request, sociallogin, form)