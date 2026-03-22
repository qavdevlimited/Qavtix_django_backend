# payments/tasks.py
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def send_split_payment_emails(split_order_id, participant_ids):
    """
    Sends payment request emails to non-initiator split participants.
    Each email contains a unique payment link with their pay_token.
    """
    from transactions.models import SplitOrder, SplitParticipant
    from django.conf import settings

    try:
        split_order = SplitOrder.objects.select_related("order__event", "initiated_by").get(
            id=split_order_id
        )
    except SplitOrder.DoesNotExist:
        logger.error(f"SplitOrder {split_order_id} not found")
        return

    event     = split_order.order.event
    initiator = split_order.initiated_by

    for pid in participant_ids:
        try:
            participant = SplitParticipant.objects.select_related("user").get(id=pid)
        except SplitParticipant.DoesNotExist:
            logger.error(f"SplitParticipant {pid} not found")
            continue

        # Build payment link — FE uses pay_token to hit /payments/split/pay/<token>/
        payment_link = (
            f"{settings.FRONTEND_URL}/split-pay/{participant.pay_token}/"
        )

        subject = f"You've been invited to split tickets for {event.title}"
        body    = f"""
Hi {participant.user.first_name or participant.user.email},

{initiator.first_name or initiator.email} has invited you to split the cost of tickets for:

  Event: {event.title}
  Date:  {event.start_datetime.strftime('%A, %d %B %Y %H:%M')}
  Your share: ₦{participant.amount:,.2f} ({participant.percentage}%)

You have until {split_order.expires_at.strftime('%A, %d %B %Y %H:%M')} to complete your payment.
If you don't pay in time, the entire order will be cancelled and anyone who paid will be refunded.

Pay your share here:
{payment_link}

If you didn't expect this, you can ignore this email.

— QavTix
        """.strip()

        _send_email(to=participant.user.email, subject=subject, body=body)


@shared_task
def send_split_initiator_confirmation(participant_id):
    """
    Notifies the initiator that their payment was received and they should
    wait for others to pay.
    """
    from transactions.models import SplitParticipant

    try:
        participant = SplitParticipant.objects.select_related(
            "split_order__order__event", "user"
        ).get(id=participant_id)
    except SplitParticipant.DoesNotExist:
        return

    split_order = participant.split_order
    event       = split_order.order.event
    pending     = split_order.total_participants - split_order.paid_count

    subject = f"Your payment is confirmed — waiting for {pending} more"
    body    = f"""
Hi {participant.user.first_name or participant.user.email},

Your share of ₦{participant.amount:,.2f} has been received for {event.title}.

{pending} participant(s) still need to pay. Your tickets will be issued once everyone has paid.

Payment deadline: {split_order.expires_at.strftime('%A, %d %B %Y %H:%M')}

— QavTix
    """.strip()

    _send_email(to=participant.user.email, subject=subject, body=body)


@shared_task
def send_split_completion_emails(split_order_id):
    """
    Notifies all participants that the split is complete and tickets are issued.
    """
    from transactions.models import SplitOrder

    try:
        split_order = SplitOrder.objects.select_related("order__event").get(id=split_order_id)
    except SplitOrder.DoesNotExist:
        return

    event        = split_order.order.event
    participants = split_order.participants.select_related("user", "issued_ticket").all()

    for participant in participants:
        subject = f"Your ticket for {event.title} is confirmed!"
        body    = f"""
Hi {participant.user.first_name or participant.user.email},

All payments have been received. Your ticket for {event.title} is now active!

  Event: {event.title}
  Date:  {event.start_datetime.strftime('%A, %d %B %Y %H:%M')}
  Ticket ID: {participant.issued_ticket.id if participant.issued_ticket else 'N/A'}

See your tickets in the QavTix app.

— QavTix
        """.strip()

        _send_email(to=participant.user.email, subject=subject, body=body)


@shared_task
def send_split_refund_notification(participant_id):
    """
    Notifies a participant that their split payment was refunded.
    """
    from transactions.models import SplitParticipant

    try:
        participant = SplitParticipant.objects.select_related(
            "split_order__order__event", "user"
        ).get(id=participant_id)
    except SplitParticipant.DoesNotExist:
        return

    event = participant.split_order.order.event

    subject = f"Split payment cancelled — refund initiated for {event.title}"
    body    = f"""
Hi {participant.user.first_name or participant.user.email},

Unfortunately, not all participants completed their payment for {event.title} in time.
The split order has been cancelled.

A refund of ₦{participant.amount:,.2f} has been initiated to your original payment method.
Please allow 3-5 business days for the refund to appear.

— QavTix
    """.strip()

    _send_email(to=participant.user.email, subject=subject, body=body)


@shared_task
def expire_split_orders():
    """
    Periodic task — run every 30 minutes via Celery beat.
    Cancels expired split orders and triggers refunds.
    """
    from payments.services.checkout_service import SplitExpiryService
    SplitExpiryService().run()


# ── Helper ────────────────────────────────────────────────────────────────────

def _send_email(to, subject, body):
    """
    Sends a plain text email.
    Swap this out for your Brevo/SendGrid implementation.
    """
    from django.core.mail import send_mail
    from django.conf import settings

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")


@shared_task
def send_plan_activated_email(subscription_id):
    """Sent immediately when plan is activated."""
    from host.models import HostSubscription

    try:
        sub = HostSubscription.objects.select_related(
            "plan", "host__user"
        ).get(id=subscription_id)
    except HostSubscription.DoesNotExist:
        return

    user     = sub.host.user
    plan     = sub.plan
    cycle    = sub.billing_cycle.capitalize()
    expires  = sub.expires_at.strftime("%A, %d %B %Y") if sub.expires_at else "Never"

    subject = f"🎉 Welcome to QavTix {plan.name}!"
    body    = f"""
Hi {user.first_name or user.email},

Your {plan.name} plan is now active.

Plan:          {plan.name}
Billing Cycle: {cycle}
Amount Paid:   ₦{sub.amount_paid:,.2f}
Expires:       {expires}

You now have access to all {plan.name} features. Log in to your dashboard to get started.

— QavTix Team
    """.strip()

    _send_email(to=user.email, subject=subject, body=body)


@shared_task
def send_plan_expiry_reminder_email(subscription_id, days_remaining):
    """Sent 7 days and 1 day before expiry."""
    from host.models import HostSubscription

    try:
        sub = HostSubscription.objects.select_related(
            "plan", "host__user"
        ).get(id=subscription_id)
    except HostSubscription.DoesNotExist:
        return

    if sub.status != "active":
        return

    user    = sub.host.user
    plan    = sub.plan
    expires = sub.expires_at.strftime("%A, %d %B %Y")
    day_str = f"{days_remaining} day{'s' if days_remaining > 1 else ''}"

    subject = f"⏰ Your {plan.name} plan expires in {day_str}"
    body    = f"""
Hi {user.first_name or user.email},

Your {plan.name} plan expires in {day_str} on {expires}.

Renew your plan to keep access to all {plan.name} features.
After expiry, your account will be moved to the Free plan.

Renew now: https://qavtix.com/host/plans

— QavTix Team
    """.strip()

    _send_email(to=user.email, subject=subject, body=body)


@shared_task
def send_plan_expired_email(subscription_id):
    """Sent when plan expires."""
    from host.models import HostSubscription

    try:
        sub = HostSubscription.objects.select_related(
            "plan", "host__user"
        ).get(id=subscription_id)
    except HostSubscription.DoesNotExist:
        return

    user = sub.host.user
    plan = sub.plan

    subject = f"Your {plan.name} plan has expired"
    body    = f"""
Hi {user.first_name or user.email},

Your {plan.name} plan has expired. Your account has been moved to the Free plan.

You still have access to all your events and data, but some features are now limited.

Upgrade anytime to restore full access:
https://qavtix.com/host/plans

— QavTix Team
    """.strip()

    _send_email(to=user.email, subject=subject, body=body)


@shared_task
def expire_host_subscriptions():
    """
    Periodic — runs every 30 minutes via Celery beat.
    Expires active subscriptions past their expires_at.
    Moves host back to free plan by creating a new free subscription.
    """
    from host.models import HostSubscription
    from payments.models import HostPlan
    from django.utils import timezone

    now     = timezone.now()
    expired = HostSubscription.objects.filter(
        status="active",
        expires_at__lt=now,
    ).exclude(plan_slug="free")

    try:
        free_plan = HostPlan.objects.get(slug="free")
    except HostPlan.DoesNotExist:
        logger.error("Free plan not found — cannot expire subscriptions")
        return

    for sub in expired:
        # Mark as expired
        sub.status = "expired"
        sub.save(update_fields=["status"])

        # Create a new free subscription so mixin still works
        HostSubscription.objects.get_or_create(
            host=sub.host,
            plan_slug="free",
            status="active",
            defaults={
                "plan":          free_plan,
                "billing_cycle": "free",
                "expires_at":    None,
                "amount_paid":   0,
            },
        )

        # Send expired email
        send_plan_expired_email.delay(str(sub.id))
        logger.info(f"Subscription {sub.id} expired — host moved to free")


@shared_task
def send_plan_expiry_reminders():
    """
    Periodic — runs every hour via Celery beat.
    Sends reminders for plans expiring in 7 days and 1 day.
    Uses metadata flags to prevent duplicate reminders.
    """
    from host.models import HostSubscription
    from django.utils import timezone

    now = timezone.now()

    # 7-day reminder window (6d 23h to 7d 0h)
    window_7d_start = now + timezone.timedelta(days=6, hours=23)
    window_7d_end   = now + timezone.timedelta(days=7)

    # 1-day reminder window (23h to 24h)
    window_1d_start = now + timezone.timedelta(hours=23)
    window_1d_end   = now + timezone.timedelta(hours=24)

    # 7-day reminders
    expiring_7d = HostSubscription.objects.filter(
        status="active",
        expires_at__gte=window_7d_start,
        expires_at__lt=window_7d_end,
    ).exclude(plan_slug="free").exclude(metadata__reminder_7d_sent=True)

    for sub in expiring_7d:
        send_plan_expiry_reminder_email.delay(str(sub.id), 7)
        sub.metadata["reminder_7d_sent"] = True
        sub.save(update_fields=["metadata"])
        logger.info(f"7-day expiry reminder queued for subscription {sub.id}")

    # 1-day reminders
    expiring_1d = HostSubscription.objects.filter(
        status="active",
        expires_at__gte=window_1d_start,
        expires_at__lt=window_1d_end,
    ).exclude(plan_slug="free").exclude(metadata__reminder_1d_sent=True)

    for sub in expiring_1d:
        send_plan_expiry_reminder_email.delay(str(sub.id), 1)
        sub.metadata["reminder_1d_sent"] = True
        sub.save(update_fields=["metadata"])
        logger.info(f"1-day expiry reminder queued for subscription {sub.id}")


# ─────────────────────────────────────────────────────────────────────────────
# Add to CELERY_BEAT_SCHEDULE in settings.py:
# ─────────────────────────────────────────────────────────────────────────────
# "expire-host-subscriptions": {
#     "task":     "payments.tasks.expire_host_subscriptions",
#     "schedule": crontab(minute="*/30"),
# },
# "send-plan-expiry-reminders": {
#     "task":     "payments.tasks.send_plan_expiry_reminders",
#     "schedule": crontab(minute=0),  # every hour
# },


def _send_email(to, subject, body):
    from django.core.mail import send_mail
    from django.conf import settings
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[to],
            fail_silently=False,
        )
    except Exception as e:
        logger.error(f"Failed to send plan email to {to}: {e}")