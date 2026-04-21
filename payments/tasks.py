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
from notification.email import send_templated_email
from django.utils.safestring import mark_safe
 
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
def expire_pending_orders():
    """
    Periodic task — runs every 10 or 15 minutes.
    Cancels normal pending orders where user never completed payment.
    """
    from payments.services.checkout_service import PendingOrderExpiryService
    PendingOrderExpiryService().run()

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_pending_order_reminder_email(self, order_id: int):
    from transactions.models import Order

    try:
        order = Order.objects.select_related("event").get(id=order_id)

        # safety check
        if order.status != "pending":
            return

        event = order.event
        payment_link = order.metadata.get("checkout_url")

        send_templated_email(
            subject=f"Complete your booking for {event.title}",
            to_email=order.email,
            template_name="emails/abandoned.html",
            context={
                "first_name": order.full_name or "there",
                "order_id": str(order.id)[:8].upper(),
                "booking_date": event.start_datetime.strftime("%A, %d %B %Y %H:%M"),
                "event_title": event.title,
                "payment_link": payment_link,
                "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
            },
        )

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_booking_confirmation_email(self, order_id):
    from transactions.models import Order

    try:
        order = Order.objects.select_related("event").get(id=order_id)

        send_templated_email(
            subject=f"Booking Confirmed – {order.event.title}",
            to_email=order.email,
            template_name="emails/succesfulorder.html",
            context={
                "first_name": order.full_name or "Guest",
                "order_id": order.id,
                "event_name": order.event.title,
                "start_date": order.event.start_datetime,
                "end_date": order.event.end_datetime,
                "location": getattr(order.event, "location", ""),
                "ticket_type": ", ".join(
                    [ot.ticket.ticket_type for ot in order.tickets.all()]
                ),
                "quantity": sum(ot.quantity for ot in order.tickets.all()),
                "host_name": order.event.host.full_name,
                "host_email": order.event.host.user.email,
                "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
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
    Each email contains a unique payment link with their pay_token.
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
 
        payment_link = f"https://www.qavtix.com/split-payment/{participant.pay_token}/"
        expires_str = split_order.expires_at.strftime('%A, %d %B %Y %H:%M')
 
        email_body_html = f"""
<p class="body-text">
    {initiator.first_name or initiator.email} has invited you to split the cost of tickets for:
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
 
        context = {
            "show_order_box": False,
            "company_label": "QavTix",
            "email_title": "Split Payment Invite",
            "show_divider_after_title": True,
            "email_body_html": mark_safe(email_body_html),
            "show_items_table": False,
            "payment_boxes": False,
            "show_sign_off": True,
            "sign_off_greeting": "Thanks",
            "sign_off_name": "The QavTix Team",
            "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
            "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
        }
 
        try:
            send_templated_email(
                to_email=participant.user.email,
                subject=f"You've been invited to split tickets for {event.title}",
                template_name="emails/generic_template.html",
                context=context
            )
        except Exception as exc:
            raise self.retry(exc=exc)
 
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_split_initiator_confirmation(self, participant_id):
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
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": "Payment Confirmed",
        "show_divider_after_title": True,
        "email_body_html": mark_safe(email_body_html),
        "show_items_table": False,
        "payment_boxes": False,
        "show_sign_off": True,
        "sign_off_greeting": "Thanks",
        "sign_off_name": "The QavTix Team",
        "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
        "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
    }
 
    try:
        send_templated_email(
            to_email=participant.user.email,
            subject=f"Your payment is confirmed — waiting for {pending_str}",
            template_name="emails/generic_template.html",
            context=context
        )
    except Exception as exc:
        logger.error(f"Failed to send split initiator confirmation: {exc}")
 
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_split_completion_emails(self, split_order_id):
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
 
        context = {
            "show_order_box": False,
            "company_label": "QavTix",
            "email_title": "Your Ticket is Confirmed!",
            "show_divider_after_title": True,
            "email_body_html": mark_safe(email_body_html),
            "show_items_table": False,
            "payment_boxes": False,
            "show_sign_off": True,
            "sign_off_greeting": "Enjoy!",
            "sign_off_name": "The QavTix Team",
            "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
            "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
        }
 
        try:
            send_templated_email(
                to_email=participant.user.email,
                subject=f"Your ticket for {event.title} is confirmed!",
                template_name="emails/generic_template.html",
                context=context
            )
        except Exception as exc:
            logger.error(f"Failed to send split completion email: {exc}")
 
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_split_refund_notification(self, participant_id):
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
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": "Split Payment Cancelled",
        "show_divider_after_title": True,
        "email_body_html": mark_safe(email_body_html),
        "show_items_table": False,
        "payment_boxes": False,
        "show_sign_off": True,
        "sign_off_greeting": "Thanks",
        "sign_off_name": "The QavTix Team",
        "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
        "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
    }
 
    try:
        send_templated_email(
            to_email=participant.user.email,
            subject=f"Split payment cancelled — refund initiated for {event.title}",
            template_name="emails/generic_template.html",
            context=context
        )
    except Exception as exc:
        logger.error(f"Failed to send split refund notification: {exc}")
 
 
@shared_task
def expire_split_orders():
    """
    Periodic task — run every 30 minutes via Celery beat.
    Cancels expired split orders and triggers refunds.
    """
    from payments.services.checkout_service import SplitExpiryService
    SplitExpiryService().run()
 
 
# ─────────────────────────────────────────────────────────────────────────────
# HOST SUBSCRIPTION PLAN EMAIL TASKS
# ─────────────────────────────────────────────────────────────────────────────
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_activated_email(self, subscription_id):
    """Sent immediately when a host plan is activated."""
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
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": f"Welcome to QavTix {plan.name}!",
        "show_divider_after_title": True,
        "email_body_html": mark_safe(email_body_html),
        "show_items_table": False,
        "payment_boxes": False,
        "show_sign_off": True,
        "sign_off_greeting": "Thanks",
        "sign_off_name": "The QavTix Team",
        "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
        "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
    }
 
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"🎉 Welcome to QavTix {plan.name}!",
            template_name="emails/generic_template.html",
            context=context
        )
    except Exception as exc:
        raise self.retry(exc=exc)
 
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_expiry_reminder_email(self, subscription_id, days_remaining):
    """
    Sent 7 days and 1 day before plan expires.
    Only sent for active subscriptions — cancelled subscriptions get no reminder.
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
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": f"Your {plan.name} Plan Expires Soon",
        "show_divider_after_title": True,
        "email_body_html": mark_safe(email_body_html),
        "show_items_table": False,
        "payment_boxes": False,
        "show_sign_off": True,
        "sign_off_greeting": "Thanks",
        "sign_off_name": "The QavTix Team",
        "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
        "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
    }
 
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"⏰ Your {plan.name} plan expires in {day_str}",
            template_name="emails/generic_template.html",
            context=context
        )
    except Exception as exc:
        logger.error(f"Failed to send plan expiry reminder: {exc}")
 
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_expired_email(self, subscription_id):
    """Sent when a host plan expires — both active and cancelled plans."""
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
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": f"Your {plan.name} Plan Has Expired",
        "show_divider_after_title": True,
        "email_body_html": mark_safe(email_body_html),
        "show_items_table": False,
        "payment_boxes": False,
        "show_sign_off": True,
        "sign_off_greeting": "Thanks",
        "sign_off_name": "The QavTix Team",
        "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
        "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
    }
 
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"Your {plan.name} plan has expired",
            template_name="emails/generic_template.html",
            context=context
        )
    except Exception as exc:
        logger.error(f"Failed to send plan expired email: {exc}")
 
 
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
    """
    from host.models import HostSubscription
    from django.utils import timezone
 
    now = timezone.now()
 
    # 7-day window
    window_7d_start = now + timezone.timedelta(days=6, hours=23)
    window_7d_end   = now + timezone.timedelta(days=7)
 
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
 
    # 1-day window
    window_1d_start = now + timezone.timedelta(hours=23)
    window_1d_end   = now + timezone.timedelta(hours=24)
 
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
# ATTENDEE SUBSCRIPTION PLAN EMAIL TASKS
# ─────────────────────────────────────────────────────────────────────────────
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_activated_email_attendee(self, subscription_id):
    """Sent when an Attendee plan is activated (via popup, saved card, or webhook)"""
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
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": f"Welcome to QavTix {plan.name} Plan!",
        "show_divider_after_title": True,
        "email_body_html": mark_safe(email_body_html),
        "show_items_table": False,
        "payment_boxes": False,
        "show_sign_off": True,
        "sign_off_greeting": "Thanks",
        "sign_off_name": "The QavTix Team",
        "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
        "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
    }
 
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"🎉 Welcome to QavTix {plan.name} Plan!",
            template_name="emails/generic_template.html",
            context=context
        )
    except Exception as exc:
        raise self.retry(exc=exc)
 
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_expiry_reminder_email_attendee(self, subscription_id, days_remaining):
    """Sent 7 days and 1 day before attendee plan expires (only for active plans)"""
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
    <a href="https://www.qavtix.com/pricing">Renew now</a> to continue enjoying boosted affiliate rewards, higher ticket discounts,
    early access, and exclusive deals.
</p>
    """
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": f"Your {plan.name} Plan Expires Soon",
        "show_divider_after_title": True,
        "email_body_html": mark_safe(email_body_html),
        "show_items_table": False,
        "payment_boxes": False,
        "show_sign_off": True,
        "sign_off_greeting": "Thanks",
        "sign_off_name": "The QavTix Team",
        "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
        "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
    }
 
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"⏰ Your {plan.name} plan expires in {day_str}",
            template_name="emails/generic_template.html",
            context=context
        )
    except Exception as exc:
        logger.error(f"Failed to send attendee plan expiry reminder: {exc}")
 
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_plan_expired_email_attendee(self, subscription_id):
    """Sent when an attendee plan expires"""
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
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": f"Your {plan.name} Plan Has Expired",
        "show_divider_after_title": True,
        "email_body_html": mark_safe(email_body_html),
        "show_items_table": False,
        "payment_boxes": False,
        "show_sign_off": True,
        "sign_off_greeting": "Thanks",
        "sign_off_name": "The QavTix Team",
        "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
        "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
    }
 
    try:
        send_templated_email(
            to_email=user.email,
            subject=f"Your {plan.name} plan has expired",
            template_name="emails/generic_template.html",
            context=context
        )
    except Exception as exc:
        logger.error(f"Failed to send attendee plan expired email: {exc}")
 
 
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
        send_plan_expiry_reminder_email_attendee.delay(str(sub.id), 7)
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
        send_plan_expiry_reminder_email_attendee.delay(str(sub.id), 1)
        sub.metadata["reminder_1d_sent"] = True
        sub.save(update_fields=["metadata"])
        logger.info(f"1-day attendee expiry reminder queued for sub {sub.id}")