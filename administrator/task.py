"""
admin_auth/tasks.py

Celery tasks for admin authentication emails.
Make sure celery is configured in your project:

    # celery.py
    from celery import Celery
    app = Celery("qavtix")
    app.config_from_object("django.conf:settings", namespace="CELERY")
    app.autodiscover_tasks()

    # settings.py
    CELERY_BROKER_URL = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND = "redis://localhost:6379/0"
"""

from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,   # retry after 10s on failure
)
def send_otp_email(self, user_email: str, full_name: str, otp: str):
    """
    Sends the OTP email asynchronously via Brevo (django-anymail).
    Retries up to 3 times on failure with a 10 second delay.
    """
    try:
        send_mail(
            subject="Your QavTix Admin Login Code",
            message=(
                f"Hi {full_name},\n\n"
                f"Your one-time login code is: {otp}\n\n"
                f"This code expires in 10 minutes.\n"
                f"If you did not request this, please contact support immediately.\n\n"
                f"— QavTix Security"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            html_message=f"""
                <div style="font-family: Arial, sans-serif; max-width: 480px; margin: auto;">
                    <h2 style="color: #1a1a1a;">Admin Login Verification</h2>
                    <p>Hi <strong>{full_name}</strong>,</p>
                    <p>Use the code below to complete your login. It expires in <strong>10 minutes</strong>.</p>
                    <div style="
                        background: #f4f4f4;
                        border-radius: 8px;
                        padding: 24px;
                        text-align: center;
                        margin: 24px 0;
                    ">
                        <span style="font-size: 36px; font-weight: bold; letter-spacing: 8px; color: #1a1a1a;">
                            {otp}
                        </span>
                    </div>
                    <p style="color: #666; font-size: 13px;">
                        If you did not attempt to log in, please contact support immediately.
                    </p>
                </div>
            """,
            fail_silently=False,
        )
    except Exception as exc:
        raise self.retry(exc=exc)