# payments/tasks.py
import logging
import csv
from io import StringIO

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_attendee_data_export(self, user_id):
    from django.contrib.auth import get_user_model
    from attendee.models import AffliateEarnings, AttendeeSubscription

    User = get_user_model()

    try:
        user = User.objects.select_related("attendee_profile").get(id=user_id)
        attendee = user.attendee_profile
    except Exception as exc:
        raise self.retry(exc=exc)

    # ───────── CSV ─────────
    buffer = StringIO()
    writer = csv.writer(buffer)

    writer.writerow([
        "Full Name",
        "Email",
        "Phone",
        "Country",
        "State",
        "City",
        "Subscription Plan",
        "Subscription Status",
        "Total Affiliate Earnings",
    ])

    total_earnings = sum(
        e.earning for e in AffliateEarnings.objects.filter(attendee=attendee)
    )

    sub = AttendeeSubscription.objects.filter(
        attendee=attendee
    ).order_by("-started_at").first()

    writer.writerow([
        attendee.full_name,
        user.email,
        attendee.phone_number,
        attendee.country,
        attendee.state,
        attendee.city,
        sub.plan_slug if sub else "",
        sub.status if sub else "",
        total_earnings,
    ])

    csv_file = buffer.getvalue()
    buffer.close()

    # ───────── TEMPLATE ─────────
    html_content = render_to_string(
        "emails/export_completed.html",
        {
            "first_name": attendee.full_name or "there",
            "request_date": "Today",
            "export_type": "Full Data",
            "header_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777156477/Banner_11_vjqyfu.png",
            "footer_image_url": "https://res.cloudinary.com/dpuvtcctg/image/upload/v1777138564/Footer_5_itsjwc.png",
        },
    )

    text_content = strip_tags(html_content)

    # ───────── SEND EMAIL ─────────
    email = EmailMultiAlternatives(
        subject="Your Data Export Has Been Completed",
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )

    email.attach_alternative(html_content, "text/html")

    email.attach(
        filename="qavtix_data_export.csv",
        content=csv_file,
        mimetype="text/csv"
    )

    email.send(fail_silently=False)