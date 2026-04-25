import logging
import os
 
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
 
# ── import our template builder ──────────────────────────────────────────────
from email_templates import (
    build_email,
    body_welcome,
    body_otp,
    body_password_changed,
    body_password_reset_otp,
)
from notification.email import send_templated_email
 
logger = logging.getLogger(__name__)
 



@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_password_reset_otp_task(self, user_email: str,  otp :str):
    try:
        send_templated_email(
            subject="Your One-Time Password (OTP)",
            to_email=user_email,
            template_name="emails/otp.html",
            context={
                "otp_digits": list(otp),
                "expires_minutes": 5,
                "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777139840/iuew_1_x760pc.png",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777138564/Footer_5_itsjwc.png",
                "action_url": "#",
                "button_text": "Verify",
            },
        )
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_password_change_info_task(self, email: str, first_name: str):
    try:
        send_templated_email(
            subject="Your One-Time Password (OTP)",
             to_email=email,
            template_name="emails/passwordchange.html",
            context={
                "first_name": first_name,
                "email":email,
                "header_image_url":  "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777139840/iuew_1_x760pc.png",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
            },
        )

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_welcome_email_task(self, email: str, first_name: str):
    try:
        send_templated_email(
            subject="Welcome to QavTix! 🎉",
             to_email=email,
            template_name="emails/welcome.html",
            context={
                "first_name": first_name,
                "header_image_url":  "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777139253/Banner_1_z40nwx.png",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
            },
        )

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_host_welcome_email_task(self, email: str, first_name: str):
    try:
        send_templated_email(
            subject="Welcome to QavTix 🎉",
             to_email=email,
            template_name="emails/hostwelcome.html",
            context={
                "first_name": first_name,
                "header_image_url":  "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
            },
        )

    except Exception as exc:
        raise self.retry(exc=exc)