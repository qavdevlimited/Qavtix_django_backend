from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from rest_framework.exceptions import ValidationError

class MySocialAccountAdapter(DefaultSocialAccountAdapter):
    def populate_user(self, request, sociallogin, data):
        """
        Called when creating a user from social login.
        If email is missing, raise an error to prompt manual registration.
        """
        user = super().populate_user(request, sociallogin, data)

        # Facebook should return email
        email = sociallogin.account.extra_data.get('email') or data.get('email')
        if not email:
            raise ValidationError("Facebook did not provide an email. Please register manually.")

        user.email = email
        # Optionally generate username from first+last name
        if not user.username:
            base = (user.first_name or 'user') + (user.last_name or '')
            user.username = base[:30]  # truncate to 30 chars
        return user