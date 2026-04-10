# payments/tasks.py
import logging
import os
 
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
 
# ── import our template builder ──────────────────────────────────────────────
from email_templates import (
    build_email,
    body_incomplete_booking,
    body_welcome,
    body_otp,
    body_password_changed,
    body_booking_confirmed,
    body_plan_subscribed,
    body_verification_badge,
    body_plan_renewed,
    body_plan_renewal_failed,
    body_password_reset_otp,
)
 
logger = logging.getLogger(__name__)
 
# Resolve logo path once at import time so every task reuses it.
_LOGO_PATH: str = getattr(settings, "QAVTIX_LOGO_PATH", "")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Low-level helper
# ─────────────────────────────────────────────────────────────────────────────
 
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


# ─────────────────────────────────────────────────────────────────────────────
# Featured event tasks
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def send_featured_activation_email(featured_id):
    """Sent immediately when featured plan goes live."""
    from events.models import FeaturedEvent

    try:
        featured = FeaturedEvent.objects.select_related("event", "user").get(id=featured_id)
    except FeaturedEvent.DoesNotExist:
        return

    plan_name     = featured.metadata.get("plan_slug", "").capitalize()
    duration_days = featured.metadata.get("duration_days", "")

    subject = f'🎉 Your event "{featured.event.title}" is now featured!'
    body    = f"""
Hi {featured.user.first_name or featured.user.email},

Your event "{featured.event.title}" is now live as a featured event on QavTix.

Plan:     {plan_name}
Duration: {duration_days} day(s)
Expires:  {featured.end_date.strftime('%A, %d %B %Y %H:%M')} UTC

Your event will now appear prominently across our homepage, event feed, and search results.

— QavTix Team
    """.strip()

    _send_email(to=featured.user.email, subject=subject, body=body)


@shared_task
def send_featured_expiry_reminder_email(featured_id):
    """Sent 24 hours before featured plan expires."""
    from events.models import FeaturedEvent

    try:
        featured = FeaturedEvent.objects.select_related("event", "user").get(id=featured_id)
    except FeaturedEvent.DoesNotExist:
        return

    if featured.status != "active":
        return

    subject = f'⏰ Your featured plan for "{featured.event.title}" expires tomorrow'
    body    = f"""
Hi {featured.user.first_name or featured.user.email},

Your featured plan for "{featured.event.title}" expires in approximately 24 hours.

Expires: {featured.end_date.strftime('%A, %d %B %Y %H:%M')} UTC

Feature your event again to keep the visibility going.

— QavTix Team
    """.strip()

    _send_email(to=featured.user.email, subject=subject, body=body)


@shared_task
def send_featured_expired_email(featured_id):
    """Sent when featured plan has expired."""
    from events.models import FeaturedEvent

    try:
        featured = FeaturedEvent.objects.select_related("event", "user").get(id=featured_id)
    except FeaturedEvent.DoesNotExist:
        return

    subject = f'Your featured plan for "{featured.event.title}" has ended'
    body    = f"""
Hi {featured.user.first_name or featured.user.email},

Your featured plan for "{featured.event.title}" has now expired.

Your event remains visible in normal search results and listings.
Feature it again anytime to boost visibility.

— QavTix Team
    """.strip()

    _send_email(to=featured.user.email, subject=subject, body=body)


@shared_task
def expire_featured_events():
    """
    Periodic — runs every 30 minutes.
    Expires active featured events past their end_date.
    """
    from events.models import FeaturedEvent
    from django.utils import timezone

    now     = timezone.now()
    expired = FeaturedEvent.objects.filter(status="active", end_date__lt=now)

    for featured in expired:
        featured.status = "expired"
        featured.save(update_fields=["status"])
        send_featured_expired_email.delay(str(featured.id))
        logger.info(f"FeaturedEvent {featured.id} expired")


@shared_task
def send_featured_expiry_reminders():
    """
    Periodic — runs every hour.
    Sends reminder for plans expiring in next 24-25 hours.
    """
    from events.models import FeaturedEvent
    from django.utils import timezone

    now          = timezone.now()
    window_start = now + timezone.timedelta(hours=24)
    window_end   = now + timezone.timedelta(hours=25)

    expiring = FeaturedEvent.objects.filter(
        status="active",
        end_date__gte=window_start,
        end_date__lt=window_end,
        metadata__reminder_sent=False,
    )

    for featured in expiring:
        send_featured_expiry_reminder_email.delay(str(featured.id))
        featured.metadata["reminder_sent"] = True
        featured.save(update_fields=["metadata"])


# ─────────────────────────────────────────────────────────────────────────────
# Host subscription plan tasks
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def send_plan_activated_email(subscription_id):
    """Sent immediately when a host plan is activated."""
    from host.models import HostSubscription

    try:
        sub = HostSubscription.objects.select_related(
            "plan", "host__user"
        ).get(id=subscription_id)
    except HostSubscription.DoesNotExist:
        logger.error(f"HostSubscription {subscription_id} not found for activation email")
        return

    user    = sub.host.user
    plan    = sub.plan
    cycle   = sub.billing_cycle.capitalize()
    expires = sub.expires_at.strftime("%A, %d %B %Y") if sub.expires_at else "Never"

    subject = f"🎉 Welcome to QavTix {plan.name}!"
    body    = f"""
Hi {user.first_name or user.email},

Your {plan.name} plan is now active.

Plan:          {plan.name}
Billing Cycle: {cycle}
Amount Paid:   ₦{sub.amount_paid:,.2f}
Expires:       {expires}

You now have access to all {plan.name} features.
Log in to your dashboard to get started.

— QavTix Team
    """.strip()

    _send_email(to=user.email, subject=subject, body=body)


@shared_task
def send_plan_expiry_reminder_email(subscription_id, days_remaining):
    """
    Sent 7 days and 1 day before plan expires.
    Only sent for active subscriptions — cancelled subscriptions get no reminder.
    """
    from host.models import HostSubscription

    try:
        sub = HostSubscription.objects.select_related(
            "plan", "host__user"
        ).get(id=subscription_id)
    except HostSubscription.DoesNotExist:
        return

    # Only send for active subscriptions — cancelled ones chose to leave
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
    """Sent when a host plan expires — both active and cancelled plans."""
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

You still have access to all your events and data, but some features are
now limited under the Free plan.

Upgrade anytime to restore full access:
https://qavtix.com/host/plans

— QavTix Team
    """.strip()

    _send_email(to=user.email, subject=subject, body=body)


@shared_task
def expire_host_subscriptions():
    """
    Periodic — runs every 30 minutes via Celery beat.

    Finds both active AND cancelled subscriptions past their expires_at.
    - Active:    plan ran its full course
    - Cancelled: host cancelled but plan ran to end of paid period

    For each expired subscription:
      1. Marks as expired
      2. Creates free subscription so host is never planless
      3. Queues expiry email
    """
    from host.models import HostSubscription
    from payments.models import HostPlan
    from django.utils import timezone

    now = timezone.now()

    # Include cancelled — they still need to expire when their paid period ends
    expired = HostSubscription.objects.filter(
        status__in=["active", "cancelled"],
        expires_at__lt=now,
    ).exclude(plan_slug="free").select_related("host", "plan")

    try:
        free_plan = HostPlan.objects.get(slug="free")
    except HostPlan.DoesNotExist:
        logger.error("Free plan not found — cannot expire subscriptions. Run plan seed.")
        return

    for sub in expired:
        sub.status = "expired"
        sub.save(update_fields=["status"])

        # Ensure host always has an active free subscription after expiry
        HostSubscription.objects.get_or_create(
            host=sub.host,
            plan_slug="free",
            status="active",
            defaults={
                "plan":          free_plan,
                "billing_cycle": "free",
                "expires_at":    None,
                "amount_paid":   0,
                "metadata":      {},
            },
        )

        send_plan_expired_email.delay(str(sub.id))
        logger.info(
            f"Subscription {sub.id} expired "
            f"(host: {sub.host.id}, plan: {sub.plan_slug}) — moved to free"
        )


@shared_task
def send_plan_expiry_reminders():
    """
    Periodic — runs every hour via Celery beat.

    Sends reminder emails only for ACTIVE subscriptions expiring in:
      - 7 days (window: 6d 23h → 7d 0h)
      - 1 day  (window: 23h → 24h)

    Cancelled subscriptions get no reminder — they chose to cancel.
    Uses metadata flags to prevent duplicate reminders.
    """
    from host.models import HostSubscription
    from django.utils import timezone

    now = timezone.now()

    # 7-day window
    window_7d_start = now + timezone.timedelta(days=6, hours=23)
    window_7d_end   = now + timezone.timedelta(days=7)

    expiring_7d = HostSubscription.objects.filter(
        status="active",   # cancelled subscriptions get no reminder
        expires_at__gte=window_7d_start,
        expires_at__lt=window_7d_end,
    ).exclude(plan_slug="free").exclude(metadata__reminder_7d_sent=True)

    for sub in expiring_7d:
        send_plan_expiry_reminder_email.delay(str(sub.id), 7)
        sub.metadata["reminder_7d_sent"] = True
        sub.save(update_fields=["metadata"])
        logger.info(f"7-day expiry reminder queued for subscription {sub.id}")

    # 1-day window
    window_1d_start = now + timezone.timedelta(hours=23)
    window_1d_end   = now + timezone.timedelta(hours=24)

    expiring_1d = HostSubscription.objects.filter(
        status="active",   # cancelled subscriptions get no reminder
        expires_at__gte=window_1d_start,
        expires_at__lt=window_1d_end,
    ).exclude(plan_slug="free").exclude(metadata__reminder_1d_sent=True)

    for sub in expiring_1d:
        send_plan_expiry_reminder_email.delay(str(sub.id), 1)
        sub.metadata["reminder_1d_sent"] = True
        sub.save(update_fields=["metadata"])
        logger.info(f"1-day expiry reminder queued for subscription {sub.id}")



# ====================== ATTENDEE SUBSCRIPTION EMAIL TASKS ======================

@shared_task
def send_plan_activated_email_attendee(subscription_id):
    """Sent when an Attendee plan is activated (via popup, saved card, or webhook)"""
    from attendee.models import AttendeeSubscription   # your model location

    try:
        sub = AttendeeSubscription.objects.select_related(
            "plan", "attendee__user"
        ).get(id=subscription_id)
    except AttendeeSubscription.DoesNotExist:
        logger.error(f"AttendeeSubscription {subscription_id} not found for activation email")
        return

    user    = sub.attendee.user
    plan    = sub.plan
    cycle   = sub.billing_cycle.capitalize()
    expires = sub.expires_at.strftime("%A, %d %B %Y") if sub.expires_at else "Never"

    subject = f"🎉 Welcome to QavTix {plan.name} Plan!"
    body    = f"""
Hi {user.first_name or user.email},

Your {plan.name} plan is now active.

Plan:          {plan.name}
Billing Cycle: {cycle}
Amount Paid:   ₦{sub.amount_paid:,.2f}
Expires:       {expires}

You now have access to boosted rewards, higher discount caps, early access, 
and all other {plan.name} benefits.

Log in to your dashboard to explore your new features.

— QavTix Team
    """.strip()

    _send_email(to=user.email, subject=subject, body=body)


@shared_task
def send_plan_expiry_reminder_email(subscription_id, days_remaining):
    """Sent 7 days and 1 day before attendee plan expires (only for active plans)"""
    from attendee.models import AttendeeSubscription

    try:
        sub = AttendeeSubscription.objects.select_related(
            "plan", "attendee__user"
        ).get(id=subscription_id)
    except AttendeeSubscription.DoesNotExist:
        return

    if sub.status != "active":
        return

    user    = sub.attendee.user
    plan    = sub.plan
    expires = sub.expires_at.strftime("%A, %d %B %Y")
    day_str = f"{days_remaining} day{'s' if days_remaining > 1 else ''}"

    subject = f"⏰ Your {plan.name} plan expires in {day_str}"
    body    = f"""
Hi {user.first_name or user.email},

Your {plan.name} attendee plan expires in {day_str} on {expires}.

Renew now to continue enjoying boosted affiliate rewards, higher ticket discounts,
early access, and exclusive deals.

Renew here: https://qavtix.com/attendee/plans

— QavTix Team
    """.strip()

    _send_email(to=user.email, subject=subject, body=body)


@shared_task
def send_plan_expired_email(subscription_id):
    """Sent when an attendee plan expires"""
    from attendee.models import AttendeeSubscription

    try:
        sub = AttendeeSubscription.objects.select_related(
            "plan", "attendee__user"
        ).get(id=subscription_id)
    except AttendeeSubscription.DoesNotExist:
        return

    user = sub.attendee.user
    plan = sub.plan

    subject = f"Your {plan.name} plan has expired"
    body    = f"""
Hi {user.first_name or user.email},

Your {plan.name} attendee plan has expired. Your account has been moved back to the Free plan.

You can still buy tickets and earn basic rewards, but many premium benefits are now limited.

Upgrade anytime to restore full access:
https://qavtix.com/attendee/plans

— QavTix Team
    """.strip()

    _send_email(to=user.email, subject=subject, body=body)


@shared_task
def expire_attendee_subscriptions():
    """
    Periodic task - Runs every 30 minutes.
    Expires attendee subscriptions that have passed their expires_at date.
    """
    from attendee.models import AttendeeSubscription
    from payments.models import AttendeePlan
    from django.utils import timezone

    now = timezone.now()

    expired = AttendeeSubscription.objects.filter(
        status__in=["active", "cancelled"],
        expires_at__lt=now,
    ).exclude(plan_slug="free").select_related("attendee", "plan")

    try:
        free_plan = AttendeePlan.objects.get(slug="free")
    except AttendeePlan.DoesNotExist:
        logger.error("Free AttendeePlan not found. Please seed the plans.")
        return

    for sub in expired:
        sub.status = "expired"
        sub.save(update_fields=["status"])

        # Ensure attendee always has an active free subscription
        AttendeeSubscription.objects.get_or_create(
            attendee=sub.attendee,
            plan_slug="free",
            status="active",
            defaults={
                "plan":          free_plan,
                "billing_cycle": "free",
                "expires_at":    None,
                "amount_paid":   0,
                "metadata":      {},
            },
        )

        send_plan_expired_email.delay(str(sub.id))
        logger.info(f"Attendee subscription {sub.id} expired → moved to free plan")


@shared_task
def send_attendee_plan_expiry_reminders():
    """
    Periodic task - Runs every hour.
    Sends reminders only for ACTIVE attendee subscriptions.
    """
    from attendee.models import AttendeeSubscription
    from django.utils import timezone

    now = timezone.now()

    # 7-day reminder
    window_7d_start = now + timezone.timedelta(days=6, hours=23)
    window_7d_end   = now + timezone.timedelta(days=7)

    expiring_7d = AttendeeSubscription.objects.filter(
        status="active",
        expires_at__gte=window_7d_start,
        expires_at__lt=window_7d_end,
    ).exclude(plan_slug="free").exclude(metadata__reminder_7d_sent=True)

    for sub in expiring_7d:
        send_plan_expiry_reminder_email.delay(str(sub.id), 7)
        sub.metadata["reminder_7d_sent"] = True
        sub.save(update_fields=["metadata"])
        logger.info(f"7-day attendee expiry reminder queued for sub {sub.id}")

    # 1-day reminder
    window_1d_start = now + timezone.timedelta(hours=23)
    window_1d_end   = now + timezone.timedelta(hours=24)

    expiring_1d = AttendeeSubscription.objects.filter(
        status="active",
        expires_at__gte=window_1d_start,
        expires_at__lt=window_1d_end,
    ).exclude(plan_slug="free").exclude(metadata__reminder_1d_sent=True)

    for sub in expiring_1d:
        send_plan_expiry_reminder_email.delay(str(sub.id), 1)
        sub.metadata["reminder_1d_sent"] = True
        sub.save(update_fields=["metadata"])
        logger.info(f"1-day attendee expiry reminder queued for sub {sub.id}")
# ─────────────────────────────────────────────────────────────────────────────
# Shared email helper — single definition used by all tasks above
# ─────────────────────────────────────────────────────────────────────────────

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
        logger.error(f"Failed to send email to {to}: {e}")