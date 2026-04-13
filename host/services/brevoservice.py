"""
email_campaigns/services.py

All business logic for creating, sending, and listing email campaigns.
Views call this; nothing here knows about HTTP request/response.
"""
import logging
from django.utils import timezone
from django.db import transaction

from transactions.models import Order
from host.models import EmailCampaign
from . import brevocampaign as brevo

logger = logging.getLogger(__name__)


class CampaignService:

    # ── List ──────────────────────────────────────────────────────────────────

    @staticmethod
    def get_host_campaigns(host, search=None):
        """
        Return all campaigns for the host, enriched with live Brevo stats.
        Stats are fetched in a single bulk call to avoid N+1 HTTP requests.
        """
        qs = (
            EmailCampaign.objects
            .select_related("event", "event__category")
            .prefetch_related("event__media")
            .filter(host=host)
        )

        if search:
            qs = qs.filter(campaign_name__icontains=search)

        campaigns = list(qs)

        # Bulk-fetch live stats from Brevo for all sent campaigns
        sent_ids = [
            c.brevo_campaign_id for c in campaigns
            if c.brevo_campaign_id and c.status == "sent"
        ]
        if sent_ids:
            stats_map = brevo.get_bulk_campaign_stats(sent_ids)
            for campaign in campaigns:
                if campaign.brevo_campaign_id in stats_map:
                    stats = stats_map[campaign.brevo_campaign_id]
                    # Update cached values in-place (no DB write on list — see note)
                    campaign.open_rate  = stats["open_rate"]
                    campaign.click_rate = stats["click_rate"]

            # Persist refreshed stats in bulk so the next load is fast
            EmailCampaign.objects.bulk_update(
                [c for c in campaigns if c.brevo_campaign_id in stats_map],
                ["open_rate", "click_rate"],
            )

        return campaigns

    # ── Create and Send ───────────────────────────────────────────────────────

    @staticmethod
    def create_and_send_campaign(host, data):
        """
        Single action that:
          1. Validates event ownership
          2. Collects attendees from completed orders
          3. Syncs contacts to a Brevo contact list
          4. Creates and immediately sends the campaign via Brevo
          5. Persists the campaign record with full send details

        This matches the frontend flow where create and send are one action.
        """
        from events.models import Event

        # ── Validate event ────────────────────────────────────────────────────
        try:
            event = Event.objects.get(id=data["event_id"], host=host)
        except Event.DoesNotExist:
            raise CampaignError("Event not found or does not belong to you.", 404)

        # ── Collect attendees ─────────────────────────────────────────────────
        contacts = CampaignService._build_contact_list(event)
        if not contacts:
            raise CampaignError(
                "No attendees found for this event. Cannot send to an empty list.", 400
            )

        sender_name  = data.get("sender_name")  or event.organizer_display_name
        sender_email = data.get("sender_email") or event.public_email

        # ── Save campaign record OUTSIDE the atomic block ───────────────────
        # This ensures the record persists even if the Brevo API calls fail,
        # so we can mark it as failed and the host can see it in the list.
        campaign = EmailCampaign.objects.create(
            host          = host,
            event         = event,
            campaign_name = data["campaign_name"],
            subject       = data["subject"],
            html_content  = data["html_content"],
            sender_name   = sender_name,
            sender_email  = sender_email,
            status        = "draft",
        )

        try:
            # ── All Brevo API calls in one atomic block ────────────────────────
            # If anything here fails, the campaign record above is already
            # committed so we can safely update its status to "failed".
            with transaction.atomic():
                # ── Sync contacts to Brevo list ───────────────────────────────
                # Reuse the existing Brevo list for this event if one was
                # already created by a previous campaign. This ensures we
                # never create duplicate contact lists for the same event.
                existing = (
                    EmailCampaign.objects
                    .filter(event=event, brevo_list_id__isnull=False)
                    .exclude(id=campaign.id)
                    .values_list("brevo_list_id", flat=True)
                    .first()
                )

                if existing:
                    list_id = existing
                else:
                    list_name = f"QavTix-Event-{event.id}"
                    list_id   = brevo.create_contact_list(list_name)

                # Always re-sync contacts so new ticket buyers are included
                brevo.sync_contacts_to_list(list_id, contacts)

                # ── Create and send campaign in Brevo ─────────────────────────
                brevo_campaign_id = brevo.create_email_campaign(
                    name         = campaign.campaign_name,
                    subject      = campaign.subject,
                    html_content = campaign.html_content,
                    sender_name  = sender_name,
                    sender_email = sender_email,
                    list_id      = list_id,
                )
                brevo.send_email_campaign(brevo_campaign_id)

                # ── Persist all Brevo references + final status ───────────────
                campaign.brevo_list_id     = list_id
                campaign.brevo_campaign_id = brevo_campaign_id
                campaign.status            = "sent"
                campaign.sent_at           = timezone.now()
                campaign.recipients_count  = len(contacts)
                campaign.save(update_fields=[
                    "brevo_list_id", "brevo_campaign_id",
                    "status", "sent_at", "recipients_count",
                ])

        except CampaignError:
            raise
        except Exception as exc:
            logger.exception("Campaign send failed for event %s: %s", event.id, exc)
            # Campaign row is guaranteed to exist here — safe to update
            campaign.status = "failed"
            campaign.save(update_fields=["status"])
            raise CampaignError("Failed to send campaign. Please try again.", 500)

        return campaign

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_contact_list(event) -> list[dict]:
        """
        Collect unique attendee emails + names from all completed orders
        for the event. Returns a list ready for Brevo's import endpoint.
        """
        rows = (
            Order.objects
            .filter(event=event, status="completed")
            .select_related("user__attendee_profile")
            .values(
                "user__email",
                "user__attendee_profile__full_name",
            )
            .distinct()
        )

        seen     = set()
        contacts = []
        for row in rows:
            email = row["user__email"]
            if not email or email in seen:
                continue
            seen.add(email)
            contacts.append({
                "email": email,
                "attributes": {
                    "FIRSTNAME": row["user__attendee_profile__full_name"] or "",
                },
            })
        return contacts
    

    @staticmethod
    def send_single_email(host, data):
        """
        Sends a one-off transactional email to a single recipient.
        No campaign record created — purely a direct send.
        """
        

        try:
            brevo.send_transactional_email(
            to_email      = data["recipient_email"],
            subject       = data["subject"],
            html_content  = data["html_content"],
            sender_name   = data.get("sender_name", "QavTix"),
            sender_email  = data.get("sender_email", "savieztech@gmail.com"),
        )
        except Exception as exc:
            logger.exception("Single email send failed: %s", exc)
            raise CampaignError("Failed to send email. Please try again.", 500)

    @staticmethod
    def send_single_sms(host, data):
        """
        Sends a single transactional SMS via Brevo.
        """
        sender = data.get("sender_name") or "QavTix"
        
        # Ensure sender name is valid for SMS (max 11 alphanumeric characters)
        sender = "".join(filter(str.isalnum, sender))[:11]

        try:
            # You will define this in your brevo utility file
            return brevo.send_transactional_sms(
                recipient=data["recipient_phone"],
                content=data["message"],
                sender=sender
            )
        except Exception as e:
            logger.exception("SMS send failed")
            raise CampaignError(f"Failed to send SMS: {str(e)}", 500)
        


class CampaignError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)