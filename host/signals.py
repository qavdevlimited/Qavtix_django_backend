"""
dashboard/signals.py

Call these helpers from your existing services whenever relevant things happen.
They create both an activity log entry and a notification in one shot.

Usage examples
──────────────
# In checkout_service._finalise() after order.status = "completed":
from dashboard.signals import notify_sale
notify_sale(host_user=order.event.host.user, order=order)

# In CheckInService.process_scan() after successful check-in:
from dashboard.signals import notify_checkin
notify_checkin(host_user=ticket.event.host.user, issued_ticket=ticket)

# In your withdrawal view after withdrawal is created:
from dashboard.signals import notify_withdrawal
notify_withdrawal(host_user=request.user, withdrawal=withdrawal)
"""

from .models import HostActivity, HostNotification


def notify_sale(host_user, order):
    qty   = sum(t.quantity for t in order.tickets.all())
    name  = getattr(
        getattr(order.user, "attendee_profile", None), "full_name", None
    ) or order.full_name or order.email

    message = f"{name} bought {qty}x ticket(s) for {order.event.title} — ₦{order.total_amount:,.2f}"

    HostActivity.objects.create(
        host=host_user,
        activity_type="sale",
        message=message,
        metadata={
            "order_id":    str(order.id),
            "event_id":    str(order.event.id),
            "amount":      str(order.total_amount),
            "quantity":    qty,
            "buyer_name":  name,
        },
    )
    HostNotification.objects.create(
        host=host_user,
        notification_type="sale",
        title="New Sale",
        message=message,
    )


def notify_checkin(host_user, issued_ticket):
    name = getattr(
        getattr(issued_ticket.owner, "attendee_profile", None), "full_name", None
    ) or issued_ticket.owner.email

    ticket_type = issued_ticket.order_ticket.ticket.ticket_type
    message     = f"{name} checked in with a {ticket_type} ticket for {issued_ticket.event.title}"

    HostActivity.objects.create(
        host=host_user,
        activity_type="checkin",
        message=message,
        metadata={
            "issued_ticket_id": str(issued_ticket.id),
            "event_id":         str(issued_ticket.event.id),
            "ticket_type":      ticket_type,
            "attendee_name":    name,
        },
    )
    HostNotification.objects.create(
        host=host_user,
        notification_type="checkin",
        title="Check-In",
        message=message,
    )


def notify_withdrawal(host_user, withdrawal):
    message = f"Withdrawal request of ₦{withdrawal.amount:,.2f} is {withdrawal.status}"

    HostActivity.objects.create(
        host=host_user,
        activity_type="withdrawal",
        message=message,
        metadata={
            "withdrawal_id": str(withdrawal.id),
            "amount":        str(withdrawal.amount),
            "status":        withdrawal.status,
        },
    )
    HostNotification.objects.create(
        host=host_user,
        notification_type="withdrawal",
        title="Withdrawal Update",
        message=message,
    )


def notify_refund(host_user, order):
    name    = getattr(
        getattr(order.user, "attendee_profile", None), "full_name", None
    ) or order.full_name or order.email
    message = f"Refund of ₦{order.total_amount:,.2f} processed for {name} — {order.event.title}"

    HostActivity.objects.create(
        host=host_user,
        activity_type="refund",
        message=message,
        metadata={
            "order_id":   str(order.id),
            "amount":     str(order.total_amount),
            "buyer_name": name,
        },
    )
    HostNotification.objects.create(
        host=host_user,
        notification_type="refund",
        title="Refund Processed",
        message=message,
    )