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
 
logger = logging.getLogger(__name__)
 
# Resolve logo path once at import time so every task reuses it.
_LOGO_PATH: str = getattr(settings, "QAVTIX_LOGO_PATH", "")


def _send(to: str, subject: str, title: str, body_html: str) -> None:
    """Build the branded HTML email and send it."""
    html = build_email(title=title, body_html=body_html, logo_path=_LOGO_PATH)
    # Plain-text fallback strips tags crudely — replace with bleach/html2text
    # in production if you need a polished plain-text version.
    plain = " ".join(body_html.split())  # minimal fallback
    try:
        send_mail(
            subject=subject,
            message=plain,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            html_message=html,
            fail_silently=False,
        )
    except Exception as exc:
        logger.error(f"Failed to send email to {to}: {exc}")
        raise  # allow Celery to retry if the task is configured to do so


 
@shared_task
def send_password_reset_otp_task(email: str, otp: str):
    """
    Replaces the plain send_password_reset_otp() function.
    Call with: send_password_reset_otp_task.delay(email, otp)
    """
    _send(
        to=email,
        subject="Your QavTix Password Reset Code",
        title="Password Reset Verification",
        body_html=body_password_reset_otp(otp=otp),
    )



@shared_task
def send_password_change_info_task(email: str, first_name: str):
    """
    Replaces the plain send_password_reset_otp() function.
    Call with: send_password_reset_otp_task.delay(email, otp)
    """
    _send(
        to=email,
        subject="Your QavTix Password Changed",
        title="Password Changed Confirmation",
        body_html=body_password_changed(first_name=first_name),
    )


@shared_task
def send_welcome_email_task(email: str, first_name: str):
    """
    Replaces the plain send_password_reset_otp() function.
    Call with: send_password_reset_otp_task.delay(email, otp)
    """
    _send(
        to=email,
        subject="Welcome to QavTix",
        title="Welcome!",
        body_html=body_welcome(first_name=first_name),
    )