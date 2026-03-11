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