# payments/tasks.py
import logging
import os
 
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
import csv
from io import StringIO
from django.core.mail import EmailMessage

@shared_task
def send_attendee_data_export(user_id):
    from django.contrib.auth import get_user_model
    from attendee.models import (
        GroupMember,
        AffliateEarnings,
        AttendeeSubscription,
    )

    User = get_user_model()

    try:
        user = User.objects.select_related("attendee_profile").get(id=user_id)
        attendee = user.attendee_profile
    except Exception:
        return

    # ─────────────────────────────
    # CREATE CSV IN MEMORY
    # ─────────────────────────────
    buffer = StringIO()
    writer = csv.writer(buffer)

    # Header
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

    # Aggregate earnings
    total_earnings = sum(
        e.earning for e in AffliateEarnings.objects.filter(attendee=attendee)
    )

    # Get subscription (optional: latest one)
    sub = AttendeeSubscription.objects.filter(attendee=attendee).order_by("-started_at").first()

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

    # ─────────────────────────────
    # SEND EMAIL WITH ATTACHMENT
    # ─────────────────────────────
    email = EmailMessage(
        subject="Your QavTix Data Export",
        body="Hi,\n\nYour data export is attached as a CSV file.\n\n— QavTix",
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )

    email.attach(
        filename="my_data.csv",
        content=csv_file,
        mimetype="text/csv"
    )

    email.send(fail_silently=False)