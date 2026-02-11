from django.core.mail import send_mail
from django.conf import settings

def send_password_reset_otp(email, otp):
    subject = "Your password reset code"
    message = f"""
Your password reset code is:

{otp}

This code expires in 10 minutes.
If you did not request this, ignore this email.
"""

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [email],
        fail_silently=False
    )