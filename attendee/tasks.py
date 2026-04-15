# payments/tasks.py
import logging
import os
 
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

@shared_task
def send_attendee_data_export(user_id):
    """
    Generates and sends full attendee data export via email.
    """

    from django.contrib.auth import get_user_model
    from attendee.models import (
        Attendee,
        TicketGroup,
        GroupMember,
        AffiliateLink,
        AffliateEarnings,
        FavoriteEvent,
        AccountDeletionRequest,
        AttendeeSubscription,
    )
    import json

    User = get_user_model()

    try:
        user = User.objects.select_related("attendee_profile").get(id=user_id)
        attendee = user.attendee_profile
    except Exception as e:
        return

    # ── USER CORE DATA ─────────────────────────────────────
    data = {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "date_joined": str(user.date_joined),
        },

        # ── PROFILE ────────────────────────────────────────
        "profile": {
            "full_name": attendee.full_name,
            "phone_number": attendee.phone_number,
            "country": attendee.country,
            "state": attendee.state,
            "city": attendee.city,
            "dob": str(attendee.dob) if attendee.dob else None,
            "gender": attendee.gender,
            "email_verified": attendee.email_verified,
        },

        # ── AFFILIATE EARNINGS ─────────────────────────────
        "affiliate_earnings": list(
            AffliateEarnings.objects.filter(attendee=attendee)
            .values("earning_type", "earning", "status", "created_at")
        ),


        # ── MEMBERSHIPS ───────────────────────────────────
        "group_memberships": list(
            GroupMember.objects.filter(user=user)
            .values("group__name", "joined_at")
        ),

        # ── SUBSCRIPTIONS ─────────────────────────────────
        "subscriptions": list(
            AttendeeSubscription.objects.filter(attendee=attendee)
            .values(
                "plan_slug",
                "status",
                "billing_cycle",
                "amount_paid",
                "started_at",
                "expires_at",
            )
        ),

    }

    # Convert to readable JSON
    json_data = json.dumps(data, indent=2, default=str)

    subject = "Your QavTix Data Export"
    body = f"""
Hi {user.email},

Your requested data export is ready.

Please find your data below:

{json_data}

If this email is too large, we can switch to a downloadable file link (S3/Drive) later.

— QavTix
    """.strip()

    from django.core.mail import send_mail
    from django.conf import settings

    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )