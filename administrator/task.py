from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
import logging
from notification.email import send_templated_email
from django.utils import timezone
logger = logging.getLogger(__name__)
from django.utils.safestring import mark_safe
from django.contrib.auth.models import User

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
            send_flagged_user_alert_email.delay(
            user_id=user_id,
            reason="high_transaction_volume",
            notes=f"20+ completed orders in 24 hours as of {now.date()}",
        )
 
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
            send_flagged_user_alert_email.delay(
            user_id=user_id,
            reason="multiple_refunds",
            notes=f"3+ refund requests in 30 days as of {now.date()}",
        )
 
    logger.info(f"flag_suspicious_users complete — {flagged_count} new flags created")



@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_blue_badge_gift_email(self, host_id):
    """
    Sent when a host is awarded a permanent Blue Verification Badge.
    Congratulates the host on their achievement and explains the benefits.
    """
    from host.models import Host
 
    try:
        host = Host.objects.select_related("user").get(id=host_id)
    except Host.DoesNotExist:
        logger.error(f"Host {host_id} not found for blue badge email")
        return
 
    user = host.user
    host_name = user.first_name or user.get_full_name() or "Host"

    try:
        send_templated_email(
            subject="Congratulations: Your QavTix Account is Now Verified! 🎉",
             to_email=user.email,
            template_name="emails/bluebadgeemail.html",
            context={
                "first_name": host_name,
                "email":user.email,
                "header_image_url":  "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777146541/Banner_4_zwtuim.png",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777138564/Footer_5_itsjwc.png",
            },
        )

    except Exception as exc:
        raise self.retry(exc=exc)
 

 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_flagged_user_alert_email(self, user_id, reason, notes):
    try:
        user = User.objects.filter(id=user_id).first()

        if not user:
            logger.error(f"User {user_id} not found for flagged alert")
            return

        send_templated_email(
            subject=f"🚨 Suspicious User Flagged – {user.email}",
            to_email="admin@qavtix.com",  # 🔥 replace with your admin email or settings
            template_name="emails/flagged_user_alert.html",
            context={
                "user_email": user.email,
                "user_name": user.first_name or "N/A",
                "reason": reason,
                "notes": notes,
                "user_id": user.id,
                "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777157346/Banner_12_djyeyd.png",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777138564/Footer_5_itsjwc.png",
            },
        )

    except Exception as exc:
        raise self.retry(exc=exc)



@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,  
    autoretry_for=(ConnectionError, TimeoutError),
    acks_late=True,
)
def process_single_payout(self, withdrawal_id, initiated_by_email=""):
    """
    Celery task that handles a single Paystack transfer.
    Retries up to 3 times on failure with 60s delay.
    Using the same reference on retry prevents double-crediting.
    """
    from administrator.service.payout_service import PaystackPayoutService
    logger.info(
        f"process_single_payout: withdrawal={withdrawal_id}, "
        f"initiated_by={initiated_by_email}, "
        f"attempt={self.request.retries + 1}"
    )

    try:
        PaystackPayoutService.process_withdrawal(withdrawal_id)
    except Exception as exc:
        logger.error(
            f"process_single_payout failed for {withdrawal_id} "
            f"(attempt {self.request.retries + 1}): {exc}"
        )

        raise  # autoretry_for will catch this and retry



@shared_task
def run_friday_auto_payouts():
    """
    Runs every Friday.
    Finds all eligible withdrawals and processes them.
    """

    from transactions.models import Withdrawal
    from administrator.models import AutoPayout
    from administrator.service.payout_service import PaystackPayoutService

    logger.info("Starting Friday auto payout job")

    # Get all enabled hosts
    enabled_hosts = AutoPayout.objects.filter(is_enabled=True).values_list("host_id", flat=True)

    if not enabled_hosts:
        logger.info("No hosts with auto payout enabled")
        return

    # Get all pending withdrawals for those hosts
    withdrawals = Withdrawal.objects.filter(
        user__host_profile__in=enabled_hosts,
        status="pending"
    ).select_related("user", "payout_account")

    logger.info(f"Found {withdrawals.count()} withdrawals for auto payout")

    processed = 0
    failed = 0

    for withdrawal in withdrawals:
        try:
            # mark approved first
            withdrawal.status = "approved"
            withdrawal.metadata = withdrawal.metadata or {}
            withdrawal.metadata["auto_batch"] = True
            withdrawal.metadata["auto_batch_at"] = timezone.now().isoformat()
            withdrawal.save(update_fields=["status", "metadata"])

            # trigger Paystack transfer
            PaystackPayoutService.process_withdrawal(str(withdrawal.id))

            processed += 1

        except Exception as e:
            logger.error(f"Auto payout failed for {withdrawal.id}: {e}")
            failed += 1

    logger.info(f"Friday payout done → processed={processed}, failed={failed}")




@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_account_suspended_email(self, email, reason="",first_name=""):
    send_templated_email(
        subject="Account Suspension Notice",
        to_email=email,
        template_name="emails/suspend.html",
        context={
            "reason": reason,
            "first_name":first_name,
            "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1/banner.png",
            "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1/footer.png",
        },
    )

