# payments/tasks.py

import logging
from celery import shared_task
from django.utils.safestring import mark_safe
from notification.email import send_templated_email

logger = logging.getLogger(__name__)

HEADER_IMAGE = "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg"
FOOTER_IMAGE = "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg"


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATION SETTINGS GUARD
# ─────────────────────────────────────────────────────────────────────────────

def _can_send_email(user, setting_key: str) -> bool:
    """
    Check if the user has a specific email notification enabled.

    Args:
        user:        Django user instance
        setting_key: Exact field name on NotificationSettings
                     e.g. "email_order_confirmations"

    Returns:
        True  → send the email
        False → skip silently

    Falls back to True if the user has no settings row yet,
    so new users always receive emails until they opt out.
    
    NOTE: email_account_security is ALWAYS True — never skippable.
    """
    # Account-security emails are mandatory — never gate them
    if setting_key == "email_account_security":
        return True

    try:
        ns = user.notification_settings
        return getattr(ns, setting_key, True)
    except Exception:
        # No settings row → default to True (opt-out model)
        return True


# ─────────────────────────────────────────────────────────────────────────────
# SHARED CONTEXT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _base_context(email_title: str, email_body_html: str, **overrides) -> dict:
    """Build the standard context dict used by all generic-template emails."""
    ctx = {
        "show_order_box":         False,
        "company_label":          "QavTix",
        "email_title":            email_title,
        "show_divider_after_title": True,
        "email_body_html":        mark_safe(email_body_html),
        "show_items_table":       False,
        "payment_boxes":          False,
        "show_sign_off":          True,
        "sign_off_greeting":      "Thanks",
        "sign_off_name":          "The QavTix Team",
        "header_image_url":       HEADER_IMAGE,
        "footer_image_url":       FOOTER_IMAGE,
    }
    ctx.update(overrides)
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# PERIODIC TASKS
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def expire_pending_orders():
    """Periodic — every 10-15 minutes. Cancels unpaid pending orders."""
    from payments.services.checkout_service import PendingOrderExpiryService
    PendingOrderExpiryService().run()


@shared_task
def expire_split_orders():
    """Periodic — every 30 minutes. Cancels expired split orders and triggers refunds."""
    from payments.services.checkout_service import SplitExpiryService
    SplitExpiryService().run()


@shared_task
def expire_host_subscriptions():
    """Periodic — every 30 minutes. Expires host plans and falls back to free."""
    from host.models import HostSubscription
    from payments.models import HostPlan
    from django.utils import timezone

    now = timezone.now()
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
        logger.info(f"Subscription {sub.id} expired (host: {sub.host.id}) — moved to free")


@shared_task
def send_plan_expiry_reminders():
    """Periodic — every hour. Sends 7-day and 1-day expiry reminders for host plans."""
    from host.models import HostSubscription
    from django.utils import timezone

    now = timezone.now()

    windows = [
        (now + timezone.timedelta(days=6, hours=23), now + timezone.timedelta(days=7),   7,  "reminder_7d_sent"),
        (now + timezone.timedelta(hours=23),          now + timezone.timedelta(hours=24), 1,  "reminder_1d_sent"),
    ]

    for window_start, window_end, days, meta_key in windows:
        subs = HostSubscription.objects.filter(
            status="active",
            expires_at__gte=window_start,
            expires_at__lt=window_end,
        ).exclude(plan_slug="free").exclude(**{f"metadata__{meta_key}": True})

        for sub in subs:
            send_plan_expiry_reminder_email.delay(str(sub.id), days)
            sub.metadata[meta_key] = True
            sub.save(update_fields=["metadata"])
            logger.info(f"{days}-day expiry reminder queued for subscription {sub.id}")


@shared_task
def expire_attendee_subscriptions():
    """Periodic — every 30 minutes. Expires attendee plans and falls back to free."""
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

        send_plan_expired_email_attendee.delay(str(sub.id))
        logger.info(f"Attendee subscription {sub.id} expired → moved to free plan")


@shared_task
def send_attendee_plan_expiry_reminders():
    """Periodic — every hour. Sends 7-day and 1-day expiry reminders for attendee plans."""
    from attendee.models import AttendeeSubscription
    from django.utils import timezone

    now = timezone.now()

    windows = [
        (now + timezone.timedelta(days=6, hours=23), now + timezone.timedelta(days=7),   7,  "reminder_7d_sent"),
        (now + timezone.timedelta(hours=23),          now + timezone.timedelta(hours=24), 1,  "reminder_1d_sent"),
    ]

    for window_start, window_end, days, meta_key in windows:
        subs = AttendeeSubscription.objects.filter(
            status="active",
            expires_at__gte=window_start,
            expires_at__lt=window_end,
        ).exclude(plan_slug="free").exclude(**{f"metadata__{meta_key}": True})

        for sub in subs:
            send_plan_expiry_reminder_email_attendee.delay(str(sub.id), days)
            sub.metadata[meta_key] = True
            sub.save(update_fields=["metadata"])
            logger.info(f"{days}-day attendee expiry reminder queued for sub {sub.id}")


# ─────────────────────────────────────────────────────────────────────────────
# ORDER EMAIL TASKS
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_pending_order_reminder_email(self, order_id: int):
    """
    Abandoned booking reminder.
    Gated by: email_order_confirmations
    """
    from transactions.models import Order

    try:
        order = Order.objects.select_related("event", "user").get(id=order_id)

        if order.status != "pending":
            return

        # ── Notification settings check ──────────────────────────────
        if order.user and not _can_send_email(order.user, "email_order_confirmations"):
            logger.info(f"Skipping pending order reminder for order {order_id} — user opted out")
            return

        event        = order.event
        payment_link = order.metadata.get("checkout_url")

        send_templated_email(
            subject=f"Complete your booking for {event.title}",
            to_email=order.email,
            template_name="emails/abandoned.html",
            context={
                "first_name":       order.full_name or "there",
                "order_id":         str(order.id)[:8].upper(),
                "booking_date":     event.start_datetime.strftime("%A, %d %B %Y %H:%M"),
                "event_title":      event.title,
                "payment_link":     payment_link,
                "header_image_url": HEADER_IMAGE,
                "footer_image_url": FOOTER_IMAGE,
            },
        )

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_booking_confirmation_email(self, order_id):
    """
    Booking confirmed email.
    Gated by: email_order_confirmations
    """
    from transactions.models import Order

    try:
        order = Order.objects.select_related("event", "user").get(id=order_id)

        # ── Notification settings check ──────────────────────────────
        if order.user and not _can_send_email(order.user, "email_order_confirmations"):
            logger.info(f"Skipping booking confirmation for order {order_id} — user opted out")
            return

        send_templated_email(
            subject=f"Booking Confirmed – {order.event.title}",
            to_email=order.email,
            template_name="emails/succesfulorder.html",
            context={
                "first_name":       order.full_name or "Guest",
                "order_id":         order.id,
                "event_name":       order.event.title,
                "start_date":       order.event.start_datetime,
                "end_date":         order.event.end_datetime,
                "location":         getattr(order.event, "location", ""),
                "ticket_type":      ", ".join([ot.ticket.ticket_type for ot in order.tickets.all()]),
                "quantity":         sum(ot.quantity for ot in order.tickets.all()),
                "host_name":        order.event.host.full_name,
                "host_email":       order.event.host.user.email,
                "header_image_url": HEADER_IMAGE,
                "footer_image_url": FOOTER_IMAGE,
            },
        )

    except Exception as exc:
        raise self.retry(exc=exc)


# ─────────────────────────────────────────────────────────────────────────────
# SPLIT PAYMENT EMAIL TASKS
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_split_payment_emails(self, split_order_id, participant_ids):
    """
    Sends payment request emails to non-initiator split participants.
    Gated by: email_order_confirmations
    """
    from transactions.models import SplitOrder, SplitParticipant

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


        initiator_name = initiator.first_name or initiator.get_full_name() or "Someone"
        payment_link   = f"https://www.qavtix.com/split-payment/{participant.pay_token}/"
        expires_str    = split_order.expires_at.strftime('%A, %d %B %Y %H:%M')

        email_body_html = f"""
<p class="body-text">
    {initiator_name} has invited you to split the cost of tickets for:
</p>

<div class="payment-box">
    <p class="payment-box-title">Event Details</p>
    <p class="payment-box-text">
        <strong>Event:</strong> {event.title}<br />
        <strong>Date:</strong> {event.start_datetime.strftime('%A, %d %B %Y %H:%M')}<br />
        <strong>Your Share:</strong> ₦{participant.amount:,.2f} ({participant.percentage}%)
    </p>
</div>

<p class="body-text">
    You have until <strong>{expires_str}</strong> to complete your payment.
    If you don't pay in time, the entire order will be cancelled and anyone who paid will be refunded.
</p>

<p style="text-align: center; margin: 28px 0;">
    <a href="{payment_link}" class="cta-btn">Pay Your Share</a>
</p>

<p class="body-text">
    If you didn't expect this, you can ignore this email.
</p>
        """

        try:
            send_templated_email(
                to_email=participant.user.email,
                subject=f"You've been invited to split tickets for {event.title}",
                template_name="emails/generic_template.html",
                context=_base_context("Split Payment Invite", email_body_html),
            )
        except Exception as exc:
            raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_split_initiator_confirmation(self, participant_id):
    """
    Notifies the initiator that their payment was received.
    Gated by: email_order_confirmations
    """
    from transactions.models import SplitParticipant

    try:
        participant = SplitParticipant.objects.select_related(
            "split_order__order__event", "user"
        ).get(id=participant_id)
    except SplitParticipant.DoesNotExist:
        return

    # ── Notification settings check ──────────────────────────────────
    if not _can_send_email(participant.user, "email_order_confirmations"):
        logger.info(f"Skipping split initiator confirmation for participant {participant_id} — user opted out")
        return

    split_order = participant.split_order
    event       = split_order.order.event
    pending     = split_order.total_participants - split_order.paid_count
    pending_str = f"{pending} participant{'s' if pending > 1 else ''}"

    email_body_html = f"""
<p class="body-text">
    Your share of <strong>₦{participant.amount:,.2f}</strong> has been received for <strong>{event.title}</strong>.
</p>

<div class="payment-box">
    <p class="payment-box-title">Payment Status</p>
    <p class="payment-box-text">
        {pending_str} still need to pay. Your tickets will be issued once everyone has paid.
    </p>
</div>

<p class="body-text">
    <strong>Payment deadline:</strong> {split_order.expires_at.strftime('%A, %d %B %Y %H:%M')}
</p>
    """

    try:
        send_templated_email(
            to_email=participant.user.email,
            subject=f"Your payment is confirmed — waiting for {pending_str}",
            template_name="emails/generic_template.html",
            context=_base_context("Payment Confirmed", email_body_html),
        )
    except Exception as exc:
        logger.error(f"Failed to send split initiator confirmation: {exc}")


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_split_completion_emails(self, split_order_id):
    """
    Notifies all participants that split is complete and tickets are issued.
    Gated by: email_ticket_delivery
    """
    from transactions.models import SplitOrder

    try:
        split_order = SplitOrder.objects.select_related("order__event").get(id=split_order_id)
    except SplitOrder.DoesNotExist:
        return

    event        = split_order.order.event
    participants = split_order.participants.select_related("user", "issued_ticket").all()

    for participant in participants:
        # ── Notification settings check ──────────────────────────────
        if not _can_send_email(participant.user, "email_ticket_delivery"):
            logger.info(f"Skipping split completion email for participant {participant.id} — user opted out")
            continue

        ticket_id = participant.issued_ticket.id if participant.issued_ticket else 'N/A'

        email_body_html = f"""
<p class="body-text">
    All payments have been received. Your ticket for <strong>{event.title}</strong> is now active!
</p>

<div class="payment-box">
    <p class="payment-box-title">Ticket Information</p>
    <p class="payment-box-text">
        <strong>Event:</strong> {event.title}<br />
        <strong>Date:</strong> {event.start_datetime.strftime('%A, %d %B %Y %H:%M')}<br />
        <strong>Ticket ID:</strong> {ticket_id}
    </p>
</div>

<p class="body-text">
    See your tickets in the QavTix app.
</p>
        """

        try:
            send_templated_email(
                to_email=participant.user.email,
                subject=f"Your ticket for {event.title} is confirmed!",
                template_name="emails/generic_template.html",
                context=_base_context(
                    "Your Ticket is Confirmed!",
                    email_body_html,
                    sign_off_greeting="Enjoy!"
                ),
            )
        except Exception as exc:
            logger.error(f"Failed to send split completion email: {exc}")


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_split_refund_notification(self, participant_id):
    """
    Notifies a participant that their split payment was refunded.
    Gated by: email_order_confirmations
    """
    from transactions.models import SplitParticipant

    try:
        participant = SplitParticipant.objects.select_related(
            "split_order__order__event", "user"
        ).get(id=participant_id)
    except SplitParticipant.DoesNotExist:
        return

    # ── Notification settings check ──────────────────────────────────
    if not _can_send_email(participant.user, "email_order_confirmations"):
        logger.info(f"Skipping split refund notification for participant {participant_id} — user opted out")
        return

    event = participant.split_order.order.event

    email_body_html = f"""
<p class="body-text">
    Unfortunately, not all participants completed their payment for <strong>{event.title}</strong> in time.
    The split order has been cancelled.
</p>

<div class="payment-box">
    <p class="payment-box-title">Refund Details</p>
    <p class="payment-box-text">
        A refund of <strong>₦{participant.amount:,.2f}</strong> has been initiated to your original payment method.
        Please allow 3-5 business days for the refund to appear.
    </p>
</div>
    """

    try:
        send_templated_email(
            to_email=participant.user.email,
            subject=f"Split payment cancelled — refund initiated for {event.title}",
            template_name="emails/generic_template.html",
            context=_base_context("Split Payment Cancelled", email_body_html),
        )
    except Exception as exc:
        logger.error(f"Failed to send split refund notification: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# HOST SUBSCRIPTION PLAN EMAIL TASKS
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_activated_email(self, subscription_id):
    """
    Sent when a host plan is activated.
    Gated by: email_account_security (mandatory — always sent)
    """
    from host.models import HostSubscription

    try:
        sub = HostSubscription.objects.select_related("plan", "host__user").get(id=subscription_id)
    except HostSubscription.DoesNotExist:
        logger.error(f"HostSubscription {subscription_id} not found for activation email")
        return

    user    = sub.host.user
    plan    = sub.plan
    cycle   = sub.billing_cycle.capitalize()
    expires = sub.expires_at.strftime("%A, %d %B %Y") if sub.expires_at else "Never"

    email_body_html = f"""
<p class="body-text">
    Your <strong>{plan.name}</strong> plan is now active.
</p>

<div class="payment-box">
    <p class="payment-box-title">Plan Details</p>
    <p class="payment-box-text">
        <strong>Plan:</strong> {plan.name}<br />
        <strong>Billing Cycle:</strong> {cycle}<br />
        <strong>Amount Paid:</strong> ₦{sub.amount_paid:,.2f}<br />
        <strong>Expires:</strong> {expires}
    </p>
</div>

<p class="body-text">
    You now have access to all <strong>{plan.name}</strong> features.
    <a href="https://qavtix.com/dashboard">Log in to your dashboard</a> to get started.
</p>
    """

    # Account security — always sent regardless of preferences
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"🎉 Welcome to QavTix {plan.name}!",
            template_name="emails/generic_template.html",
            context=_base_context(f"Welcome to QavTix {plan.name}!", email_body_html),
        )
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_expiry_reminder_email(self, subscription_id, days_remaining):
    """
    Sent 7 days and 1 day before host plan expires.
    Gated by: email_account_security (mandatory — always sent)
    """
    from host.models import HostSubscription

    try:
        sub = HostSubscription.objects.select_related("plan", "host__user").get(id=subscription_id)
    except HostSubscription.DoesNotExist:
        return

    if sub.status != "active":
        return

    user    = sub.host.user
    plan    = sub.plan
    expires = sub.expires_at.strftime("%A, %d %B %Y")
    day_str = f"{days_remaining} day{'s' if days_remaining > 1 else ''}"

    email_body_html = f"""
<p class="body-text">
    Your <strong>{plan.name}</strong> plan expires in <strong>{day_str}</strong> on <strong>{expires}</strong>.
</p>

<p class="body-text">
    <a href="https://www.qavtix.com/pricing">Renew your plan</a> to keep access to all {plan.name} features.
    After expiry, your account will be moved to the Free plan.
</p>
    """

    # Account security — always sent regardless of preferences
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"⏰ Your {plan.name} plan expires in {day_str}",
            template_name="emails/generic_template.html",
            context=_base_context(f"Your {plan.name} Plan Expires Soon", email_body_html),
        )
    except Exception as exc:
        logger.error(f"Failed to send plan expiry reminder: {exc}")


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_expired_email(self, subscription_id):
    """
    Sent when a host plan expires.
    Gated by: email_account_security (mandatory — always sent)
    """
    from host.models import HostSubscription

    try:
        sub = HostSubscription.objects.select_related("plan", "host__user").get(id=subscription_id)
    except HostSubscription.DoesNotExist:
        return

    user = sub.host.user
    plan = sub.plan

    email_body_html = f"""
<p class="body-text">
    Your <strong>{plan.name}</strong> plan has expired. Your account has been moved to the Free plan.
</p>

<p class="body-text">
    You still have access to all your events and data, but some features are
    now limited under the Free plan.
</p>

<p class="body-text">
    <a href="https://www.qavtix.com/pricing">Upgrade anytime</a> to restore full access.
</p>
    """

    # Account security — always sent regardless of preferences
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"Your {plan.name} plan has expired",
            template_name="emails/generic_template.html",
            context=_base_context(f"Your {plan.name} Plan Has Expired", email_body_html),
        )
    except Exception as exc:
        logger.error(f"Failed to send plan expired email: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# ATTENDEE SUBSCRIPTION PLAN EMAIL TASKS
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_activated_email_attendee(self, subscription_id):
    """
    Sent when an attendee plan is activated.
    Gated by: email_account_security (mandatory — always sent)
    """
    from attendee.models import AttendeeSubscription

    try:
        sub = AttendeeSubscription.objects.select_related("plan", "attendee__user").get(id=subscription_id)
    except AttendeeSubscription.DoesNotExist:
        logger.error(f"AttendeeSubscription {subscription_id} not found for activation email")
        return

    user    = sub.attendee.user
    plan    = sub.plan
    cycle   = sub.billing_cycle.capitalize()
    expires = sub.expires_at.strftime("%A, %d %B %Y") if sub.expires_at else "Never"

    email_body_html = f"""
<p class="body-text">
    Your <strong>{plan.name}</strong> plan is now active.
</p>

<div class="payment-box">
    <p class="payment-box-title">Plan Details</p>
    <p class="payment-box-text">
        <strong>Plan:</strong> {plan.name}<br />
        <strong>Billing Cycle:</strong> {cycle}<br />
        <strong>Amount Paid:</strong> ₦{sub.amount_paid:,.2f}<br />
        <strong>Expires:</strong> {expires}
    </p>
</div>

<p class="body-text">
    You now have access to boosted rewards, higher discount caps, early access,
    and all other <strong>{plan.name}</strong> benefits.
</p>

<p class="body-text">
    <a href="https://qavtix.com/dashboard">Log in to your dashboard</a> to explore your new features.
</p>
    """

    # Account security — always sent regardless of preferences
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"🎉 Welcome to QavTix {plan.name} Plan!",
            template_name="emails/generic_template.html",
            context=_base_context(f"Welcome to QavTix {plan.name} Plan!", email_body_html),
        )
    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_expiry_reminder_email_attendee(self, subscription_id, days_remaining):
    """
    Sent 7 and 1 day before attendee plan expires.
    Gated by: email_account_security (mandatory — always sent)
    """
    from attendee.models import AttendeeSubscription

    try:
        sub = AttendeeSubscription.objects.select_related("plan", "attendee__user").get(id=subscription_id)
    except AttendeeSubscription.DoesNotExist:
        return

    if sub.status != "active":
        return

    user    = sub.attendee.user
    plan    = sub.plan
    expires = sub.expires_at.strftime("%A, %d %B %Y")
    day_str = f"{days_remaining} day{'s' if days_remaining > 1 else ''}"

    email_body_html = f"""
<p class="body-text">
    Your <strong>{plan.name}</strong> attendee plan expires in <strong>{day_str}</strong> on <strong>{expires}</strong>.
</p>

<p class="body-text">
    <a href="https://www.qavtix.com/pricing">Renew now</a> to continue enjoying boosted affiliate rewards,
    higher ticket discounts, early access, and exclusive deals.
</p>
    """

    # Account security — always sent regardless of preferences
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"⏰ Your {plan.name} plan expires in {day_str}",
            template_name="emails/generic_template.html",
            context=_base_context(f"Your {plan.name} Plan Expires Soon", email_body_html),
        )
    except Exception as exc:
        logger.error(f"Failed to send attendee plan expiry reminder: {exc}")


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_expired_email_attendee(self, subscription_id):
    """
    Sent when an attendee plan expires.
    Gated by: email_account_security (mandatory — always sent)
    """
    from attendee.models import AttendeeSubscription

    try:
        sub = AttendeeSubscription.objects.select_related("plan", "attendee__user").get(id=subscription_id)
    except AttendeeSubscription.DoesNotExist:
        return

    user = sub.attendee.user
    plan = sub.plan

    email_body_html = f"""
<p class="body-text">
    Your <strong>{plan.name}</strong> attendee plan has expired. Your account has been moved back to the Free plan.
</p>

<p class="body-text">
    You can still buy tickets and earn basic rewards, but many premium benefits are now limited.
</p>

<p class="body-text">
    <a href="https://www.qavtix.com/pricing">Upgrade anytime</a> to restore full access.
</p>
    """

    # Account security — always sent regardless of preferences
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"Your {plan.name} plan has expired",
            template_name="emails/generic_template.html",
            context=_base_context(f"Your {plan.name} Plan Has Expired", email_body_html),
        )
    except Exception as exc:
        logger.error(f"Failed to send attendee plan expired email: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# BLUE BADGE GIFTING EMAIL TASK
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_blue_badge_gift_email(self, host_id):
    """
    Sent when a host is awarded a permanent Blue Verification Badge.
    Gated by: email_account_security (mandatory — always sent)
    """
    from host.models import Host

    try:
        host = Host.objects.select_related("user").get(id=host_id)
    except Host.DoesNotExist:
        logger.error(f"Host {host_id} not found for blue badge email")
        return

    user      = host.user
    host_name = user.first_name or user.get_full_name() or "Host"

    email_body_html = f"""
<p class="body-text">
    Congratulations, <strong>{host_name}</strong>! Your QavTix account has been awarded a
    <strong>permanent Blue Verification Badge</strong>.
</p>

<p class="body-text">
    This recognition is given to organizers who consistently meet our platform guidelines
    through their activity, reliability, and engagement. Your commitment to creating quality
    events and maintaining trust within the QavTix community has not gone unnoticed.
</p>

<div class="payment-box">
    <p class="payment-box-title">What This Means for You</p>
    <p class="payment-box-text">
        <strong>✓</strong> A permanent Blue badge displayed on your profile<br />
        <strong>✓</strong> Increased trust and credibility with attendees<br />
        <strong>✓</strong> Stronger visibility across the QavTix platform
    </p>
</div>

<div class="payment-box">
    <p class="payment-box-title">Why You Received This Badge</p>
    <p class="payment-box-text">
        You've demonstrated:<br />
        <strong>•</strong> Consistent event activity<br />
        <strong>•</strong> Positive engagement with attendees<br />
        <strong>•</strong> Adherence to QavTix policies and standards
    </p>
</div>

<p class="body-text">
    This badge is yours to keep as a mark of trust and excellence on QavTix.
    Keep hosting, growing, and delivering great experiences — we're proud to have you on the platform.
</p>

<p class="body-text">
    If you have any questions, feel free to reach out to our support team at
    <a href="mailto:support@qavtix.com">support@qavtix.com</a>.
</p>
    """

    # Account security — always sent regardless of preferences
    try:
        send_templated_email(
            to_email=user.email,
            subject="You've Earned Your Permanent QavTix Verification Badge 🎉",
            template_name="emails/generic_template.html",
            context=_base_context(
                "You've Earned Your Permanent QavTix Verification Badge 🎉",
                email_body_html,
                sign_off_greeting="Congratulations once again,",
            ),
        )
        logger.info(f"Blue badge email sent to host {host_id} ({user.email})")
    except Exception as exc:
        logger.error(f"Failed to send blue badge email to host {host_id}: {exc}")
        raise self.retry(exc=exc)