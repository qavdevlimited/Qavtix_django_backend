# payments/tasks.py — ADD these tasks to your existing tasks file

from celery import shared_task
import logging

from notification.email import send_templated_email

logger = logging.getLogger(__name__)
from django.utils.safestring import mark_safe

@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_featured_activation_email(self, featured_id):
    from transactions.models import FeaturedEvent

    try:
        featured = FeaturedEvent.objects.select_related("event", "user").get(id=featured_id)

        plan_name = (featured.metadata.get("plan_slug") or "").capitalize()

        send_templated_email(
            subject=f"🎉 Your event is now featured – {featured.event.title}",
            to_email=featured.user.email,
            template_name="emails/featured.html",
            context={
                "first_name": featured.user.first_name or "there",
                "order_number": featured.id,
                "event_name": featured.event.title,
                "plan_name": plan_name,
                "duration_days": featured.metadata.get("duration_days"),
                "start_date": featured.event.start_datetime,
                "end_date": featured.event.end_datetime,
                "renewal_date": featured.end_date,
                "subscription_management_url": "https://qavtix.com/dashboard/subscriptions",
                "payment_activity_url": "https://payment.qavtix.com",
                "help_center_url": "https://qavtix.com/help",
                "terms_url": "https://qavtix.com/terms",
                "refund_url": "https://qavtix.com/refund",
                "privacy_url": "https://qavtix.com/privacy",
                "cancel_url": "https://qavtix.com/dashboard/subscriptions/cancel",
                "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636184/iuui1_xtvob1.svg",
                "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1776636195/iuui2_epngft.svg",
            },
        )

    except Exception as exc:
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_featured_expiry_reminder_email(self, featured_id):
    """
    Sent 24 hours before a featured plan expires.
    Reminds the host to renew if they want continued visibility boost.
    """
    from transactions.models import FeaturedEvent
 
    try:
        featured = FeaturedEvent.objects.select_related("event", "user").get(id=featured_id)
    except FeaturedEvent.DoesNotExist:
        logger.error(f"FeaturedEvent {featured_id} not found for expiry reminder")
        return
 
    user = featured.user
    event = featured.event
    end_date_str = featured.end_date.strftime("%A, %d %B %Y %H:%M")
    renewal_link = f"https://www.qavtix.com/events/{event.slug}/feature/"
 
    email_body_html = f"""
<p class="body-text">
    Your featured plan for <strong>{event.title}</strong> expires in <strong>24 hours</strong> on <strong>{end_date_str}</strong>.
</p>
 
<div class="payment-box">
    <p class="payment-box-title">Featured Plan Benefits</p>
    <p class="payment-box-text">
        <strong>✓</strong> Top placement in search results<br />
        <strong>✓</strong> Premium visibility across QavTix<br />
        <strong>✓</strong> Increased ticket sales potential<br />
        <strong>✓</strong> Featured badge on your event
    </p>
</div>
 
<p class="body-text">
    Don't lose your visibility boost! <a href="{renewal_link}">Renew your featured plan</a> before it expires 
    to keep your event at the top of search results.
</p>
 
<p class="body-text">
    If you choose not to renew, your event will remain visible in normal search results.
</p>
    """
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": "Your Featured Plan Expires Tomorrow",
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
            subject=f"⏰ Your featured plan for {event.title} expires tomorrow",
            template_name="emails/generic_template.html",
            context=context
        )
        logger.info(f"Featured expiry reminder sent to user {user.id} for event {event.id}")
    except Exception as exc:
        logger.error(f"Failed to send featured expiry reminder: {exc}")
        raise self.retry(exc=exc)
 
 
@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_featured_expired_email(self, featured_id):
    """
    Sent when a featured plan expires.
    Notifies the host that their featured plan has ended.
    """
    from transactions.models import FeaturedEvent
 
    try:
        featured = FeaturedEvent.objects.select_related("event", "user").get(id=featured_id)
    except FeaturedEvent.DoesNotExist:
        logger.error(f"FeaturedEvent {featured_id} not found for expiry email")
        return
 
    user = featured.user
    event = featured.event
    renewal_link = f"https://www.qavtix.com/events/{event.slug}/feature/"
 
    email_body_html = f"""
<p class="body-text">
    Your featured plan for <strong>{event.title}</strong> has now expired.
</p>
 
<div class="payment-box">
    <p class="payment-box-title">What Changed</p>
    <p class="payment-box-text">
        Your event is no longer featured at the top of search results.
        However, it remains visible in normal search results and listings.
    </p>
</div>
 
<p class="body-text">
    <strong>Want to boost visibility again?</strong> 
    <a href="{renewal_link}">Feature your event again</a> anytime to get back on top.
</p>
 
<div class="payment-box">
    <p class="payment-box-title">Featured Plan Features</p>
    <p class="payment-box-text">
        <strong>✓</strong> Premium placement in search results<br />
        <strong>✓</strong> Featured badge on your event<br />
        <strong>✓</strong> Increased visibility across the platform<br />
        <strong>✓</strong> Higher ticket sales potential
    </p>
</div>
 
<p class="body-text">
    Your event details and tickets remain active and available for purchase.
</p>
    """
 
    context = {
        "show_order_box": False,
        "company_label": "QavTix",
        "email_title": "Your Featured Plan Has Ended",
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
            subject=f"Your featured plan for {event.title} has ended",
            template_name="emails/generic_template.html",
            context=context
        )
        logger.info(f"Featured expired email sent to user {user.id} for event {event.id}")
    except Exception as exc:
        logger.error(f"Failed to send featured expired email: {exc}")
 
 
@shared_task
def expire_featured_events():
    """
    Periodic — runs every 30 minutes via Celery beat.
    
    Expires active featured events that have passed their end_date.
    Sends expiry notification email to the host.
    """
    from transactions.models import FeaturedEvent
    from django.utils import timezone
 
    now = timezone.now()
    expired = FeaturedEvent.objects.filter(status="active", end_date__lt=now)
 
    for featured in expired:
        featured.status = "expired"
        featured.save(update_fields=["status"])
        send_featured_expired_email.delay(str(featured.id))
        logger.info(f"FeaturedEvent {featured.id} expired for event {featured.event.id}")
 
 
@shared_task
def send_featured_expiry_reminders():
    """
    Periodic — runs every hour via Celery beat.
    
    Sends reminder emails for featured plans expiring in the next 24-25 hours.
    Uses a 1-hour window to prevent duplicate reminders.
    Only sends to active featured events that haven't already received a reminder.
    """
    from transactions.models import FeaturedEvent
    from django.utils import timezone
 
    now = timezone.now()
    
    # 24-hour window: between 24 and 25 hours from now
    window_start = now + timezone.timedelta(hours=24)
    window_end = now + timezone.timedelta(hours=25)
 
    expiring = FeaturedEvent.objects.filter(
        status="active",
        end_date__gte=window_start,
        end_date__lt=window_end,
    ).exclude(metadata__reminder_sent=True)
 
    for featured in expiring:
        send_featured_expiry_reminder_email.delay(str(featured.id))
        featured.metadata["reminder_sent"] = True
        featured.save(update_fields=["metadata"])
        logger.info(f"24-hour expiry reminder queued for featured event {featured.id}")
 


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