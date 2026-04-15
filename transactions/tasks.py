# payments/tasks.py — ADD these tasks to your existing tasks file

from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def send_featured_activation_email(featured_id):
    """Sent immediately when featured plan goes live."""
    from transactions.models import FeaturedEvent

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
    from transactions.models import FeaturedEvent

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
    """Sent when featured plan expires."""
    from transactions.models import FeaturedEvent

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
    from transactions.models import FeaturedEvent
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
    1-hour window prevents duplicate reminders.
    """
    from transactions.models import FeaturedEvent
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
        logger.error(f"Failed to send featured email to {to}: {e}")