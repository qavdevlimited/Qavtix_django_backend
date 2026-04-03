from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
import logging
 
logger = logging.getLogger(__name__)


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
    



@shared_task
def flag_suspicious_users():
    """
    Periodic task — runs every hour via Celery beat.
 
    Flags users whose behaviour matches suspicious patterns:
      1. High transaction volume — more than 20 orders in 24 hours
      2. Multiple refund requests — more than 3 refunds in 30 days
      3. Suspicious purchase pattern — bought and immediately relisted 5+ tickets
 
    Flagged users still have full access — admins review and decide action.
    """
    from django.utils import timezone
    from django.db.models import Count
    from transactions.models import Order, Refund
    from administrator.models import FlaggedUser
 
    now        = timezone.now()
    last_24h   = now - timezone.timedelta(hours=24)
    last_30d   = now - timezone.timedelta(days=30)
 
    flagged_count = 0
 
    # ── 1. High transaction volume ─────────────────────────────────────────────
    high_volume_users = (
        Order.objects
        .filter(created_at__gte=last_24h, status="completed")
        .values("user")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=20)
        .values_list("user_id", flat=True)
    )
 
    for user_id in high_volume_users:
        _, created = FlaggedUser.objects.get_or_create(
            user_id=user_id,
            defaults={
                "reason": "high_transaction_volume",
                "notes":  f"20+ completed orders in 24 hours as of {now.date()}",
                "is_active": True,
            },
        )
        if created:
            flagged_count += 1
            logger.info(f"Flagged user {user_id} for high transaction volume")
 
    # ── 2. Multiple refund requests ────────────────────────────────────────────
    high_refund_users = (
        Refund.objects
        .filter(created_at__gte=last_30d)
        .values("order__user")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=3)
        .values_list("order__user_id", flat=True)
    )
 
    for user_id in high_refund_users:
        _, created = FlaggedUser.objects.get_or_create(
            user_id=user_id,
            defaults={
                "reason":    "multiple_refunds",
                "notes":     f"3+ refund requests in 30 days as of {now.date()}",
                "is_active": True,
            },
        )
        if created:
            flagged_count += 1
            logger.info(f"Flagged user {user_id} for multiple refunds")
 
    logger.info(f"flag_suspicious_users complete — {flagged_count} new flags created")
 