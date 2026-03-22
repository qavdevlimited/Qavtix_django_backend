"""
signals.py

Django signals that fire automatically when models change.
Wire these up in your app's apps.py ready() method:

    class HostConfig(AppConfig):
        name = "host"

        def ready(self):
            import host.signals  # noqa
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import F


# ── Order ──────────────────────────────────────────────────────────────────────

@receiver(post_save, sender="transactions.Order")
def on_order_save(sender, instance, created, **kwargs):
    """
    New completed order  → sale activity + notification
    Order flipped to refunded → refund activity + notification
    """
    if not getattr(instance, "event", None):
        return
    try:
        host_user = instance.event.host.user
    except Exception:
        return

    if instance.status == "completed":
        _notify_sale(host_user, instance)

    elif not created and instance.status == "refunded":
        _notify_refund(host_user, instance)


# ── Refund ─────────────────────────────────────────────────────────────────────

@receiver(post_save, sender="transactions.Refund")
def on_refund_status_change(sender, instance, created, **kwargs):
    """
    Refund status changed to processed → notify host.
    Creation is handled by on_order_save above.
    """
    if created or instance.status != "processed":
        return
    try:
        host_user = instance.order.event.host.user
    except Exception:
        return

    _create_notification(
        host_user=host_user,
        notification_type="refund",
        title="Refund Processed",
        message=(
            f"Refund of ₦{instance.amount:,.2f} for "
            f"{instance.order.event.title} has been processed."
        ),
    )


# ── CheckIn ────────────────────────────────────────────────────────────────────

@receiver(post_save, sender="host.CheckIn")
def on_checkin_save(sender, instance, created, **kwargs):
    """First successful scan only."""
    if not created or instance.status != "checked_in" or not instance.issued_ticket:
        return
    try:
        host_user = instance.issued_ticket.event.host.user
    except Exception:
        return

    _notify_checkin(host_user, instance.issued_ticket)


# ── Withdrawal ─────────────────────────────────────────────────────────────────

@receiver(post_save, sender="transactions.Withdrawal")
def on_withdrawal_save(sender, instance, created, **kwargs):
    """
    Created          → pending activity log
    → approved/paid/rejected → activity + notification
    """
    try:
        host_user = instance.user
    except Exception:
        return

    if created:
        _create_activity(
            host_user=host_user,
            activity_type="withdrawal",
            message=f"Withdrawal request of ₦{instance.amount:,.2f} submitted.",
            metadata={
                "withdrawal_id": str(instance.id),
                "amount":        str(instance.amount),
                "status":        "pending",
            },
        )
        return

    status_messages = {
        "approved": f"Withdrawal of ₦{instance.amount:,.2f} has been approved.",
        "paid":     f"Withdrawal of ₦{instance.amount:,.2f} has been paid out.",
        "rejected": f"Withdrawal of ₦{instance.amount:,.2f} was rejected.",
    }
    msg = status_messages.get(instance.status)
    if not msg:
        return

    _create_activity(
        host_user=host_user,
        activity_type="withdrawal",
        message=msg,
        metadata={
            "withdrawal_id": str(instance.id),
            "amount":        str(instance.amount),
            "status":        instance.status,
        },
    )
    _create_notification(
        host_user=host_user,
        notification_type="withdrawal",
        title="Withdrawal Update",
        message=msg,
    )


# ── Event view / click helpers ─────────────────────────────────────────────────
# NOTE: Django signals do NOT fire on queryset .update() calls.
# These are plain functions — call them directly from your views.

def increment_event_views(event_id):
    """
    Call in your public event DETAIL view.
    Uses F() to avoid race conditions under concurrent requests.
    """
    from events.models import Event
    Event.objects.filter(id=event_id).update(views_count=F("views_count") + 1)


def increment_event_clicks(event_id):
    """
    Call in your public event LISTING view when a user clicks an event card.
    """
    from events.models import Event
    Event.objects.filter(id=event_id).update(clicks_count=F("clicks_count") + 1)


# ── Private helpers ────────────────────────────────────────────────────────────

def _buyer_name(order):
    attendee = getattr(order.user, "attendee_profile", None) if order.user else None
    return attendee.full_name if attendee else (order.full_name or order.email)


def _notify_sale(host_user, order):
    try:
        qty  = sum(t.quantity for t in order.tickets.all())
        name = _buyer_name(order)
        msg  = (
            f"{name} bought {qty}x ticket(s) for "
            f"{order.event.title} — ₦{order.total_amount:,.2f}"
        )
        _create_activity(
            host_user=host_user,
            activity_type="sale",
            message=msg,
            metadata={
                "order_id":   str(order.id),
                "event_id":   str(order.event.id),
                "amount":     str(order.total_amount),
                "quantity":   qty,
                "buyer_name": name,
            },
        )
        _create_notification(
            host_user=host_user,
            notification_type="sale",
            title="New Sale",
            message=msg,
        )
    except Exception:
        pass


def _notify_refund(host_user, order):
    try:
        name = _buyer_name(order)
        msg  = (
            f"Refund of ₦{order.total_amount:,.2f} for "
            f"{name} — {order.event.title}"
        )
        _create_activity(
            host_user=host_user,
            activity_type="refund",
            message=msg,
            metadata={
                "order_id": str(order.id),
                "amount":   str(order.total_amount),
            },
        )
        _create_notification(
            host_user=host_user,
            notification_type="refund",
            title="Refund Initiated",
            message=msg,
        )
    except Exception:
        pass


def _notify_checkin(host_user, issued_ticket):
    try:
        attendee    = getattr(issued_ticket.owner, "attendee_profile", None)
        name        = attendee.full_name if attendee else issued_ticket.owner.email
        ticket_type = issued_ticket.order_ticket.ticket.ticket_type
        msg         = (
            f"{name} checked in with a {ticket_type} ticket "
            f"for {issued_ticket.event.title}"
        )
        _create_activity(
            host_user=host_user,
            activity_type="checkin",
            message=msg,
            metadata={
                "issued_ticket_id": str(issued_ticket.id),
                "event_id":         str(issued_ticket.event.id),
                "ticket_type":      ticket_type,
                "attendee_name":    name,
            },
        )
        _create_notification(
            host_user=host_user,
            notification_type="checkin",
            title="Check-In",
            message=msg,
        )
    except Exception:
        pass


def _create_activity(host_user, activity_type, message, metadata=None):
    from .models import HostActivity
    HostActivity.objects.create(
        host=host_user,
        activity_type=activity_type,
        message=message,
        metadata=metadata or {},
    )


def _create_notification(host_user, notification_type, title, message):
    from .models import HostNotification
    HostNotification.objects.create(
        host=host_user,
        notification_type=notification_type,
        title=title,
        message=message,
    )


import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender="host.Host")
def create_free_subscription(sender, instance, created, **kwargs):
    """
    Automatically creates a free HostSubscription whenever a new Host is created.
    This ensures every host always has an active subscription record so
    the PlanFeatureMixin never gets a None subscription.
    """
    if not created:
        return

    from host.models import HostSubscription
    from payments.models import HostPlan

    try:
        free_plan = HostPlan.objects.get(slug="free")
    except HostPlan.DoesNotExist:
        logger.warning(
            f"Free plan not found when creating subscription for host {instance.id}. "
            f"Run the plan seed command to fix this."
        )
        return

    subscription, was_created = HostSubscription.objects.get_or_create(
        host=instance,
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

    if was_created:
        logger.info(f"Free subscription created for host {instance.id}")
    else:
        logger.info(f"Free subscription already exists for host {instance.id}")