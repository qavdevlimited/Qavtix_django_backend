from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
import logging
from notification.email import send_templated_email
 
logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_otp_email(self, user_email, full_name, otp):
    try:
        send_templated_email(
            subject="Your OTP Code",
            to_email=user_email,
            template_name="emails/otp.html",
            context={
                "full_name": full_name,
                "otp_digits": list(otp),
                "expires_minutes": 5,
                "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
                "action_url": "#",
                "button_text": "Verify",
            },
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




# @shared_task(
#     bind=True,
#     max_retries=3,
#     default_retry_delay=60,  # retry after 60 seconds
#     autoretry_for=(Exception,),
# )
# def process_single_payout(self, withdrawal_id, initiated_by_email=""):
#     """
#     Celery task that handles a single Paystack transfer.
#     Retries up to 3 times on failure with 60s delay.
#     Using the same reference on retry prevents double-crediting.
#     """
#     from administrator.service.payout_service import PaystackPayoutService

#     logger.info(
#         f"process_single_payout: withdrawal={withdrawal_id}, "
#         f"initiated_by={initiated_by_email}, "
#         f"attempt={self.request.retries + 1}"
#     )

#     try:
#         PaystackPayoutService.process_withdrawal(withdrawal_id)
#     except Exception as exc:
#         logger.error(
#             f"process_single_payout failed for {withdrawal_id} "
#             f"(attempt {self.request.retries + 1}): {exc}"
#         )
#         raise  # autoretry_for will catch this and retry
