

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
        qs = (
            EmailCampaign.objects
            .select_related("event", "event__category")
            .prefetch_related("event__media")
            .filter(host=host)
        )

        if search:
            qs = qs.filter(campaign_name__icontains=search)

        campaigns = list(qs)

        sent_ids = [
            c.brevo_campaign_id for c in campaigns
            if c.brevo_campaign_id and c.status == "sent"
        ]
        if sent_ids:
            stats_map = brevo.get_bulk_campaign_stats(sent_ids)
            for campaign in campaigns:
                if campaign.brevo_campaign_id in stats_map:
                    stats = stats_map[campaign.brevo_campaign_id]
                    campaign.open_rate  = stats["open_rate"]
                    campaign.click_rate = stats["click_rate"]

            EmailCampaign.objects.bulk_update(
                [c for c in campaigns if c.brevo_campaign_id in stats_map],
                ["open_rate", "click_rate"],
            )

        return campaigns

    # ── Create and Send Campaign ──────────────────────────────────────────────

    @staticmethod
    def create_and_send_campaign(host, data):
        """
        Enforces email quota before sending.
        Quota is checked against the number of contacts (recipients) BEFORE sending.
        If quota is insufficient the whole send is blocked — no partial sends.
        """
        from events.models import Event
        from host.services.campaign_quota_service import CampaignQuotaService, QuotaExceededError

        try:
            event = Event.objects.get(id=data["event_id"], host=host)
        except Event.DoesNotExist:
            raise CampaignError("Event not found or does not belong to you.", 404)

        contacts = CampaignService._build_contact_list(event)
        if not contacts:
            raise CampaignError(
                "No attendees found for this event. Cannot send to an empty list.", 400
            )

        # ── Quota check BEFORE doing anything ────────────────────────────────
        # We check against contacts count — that's how many sends this will consume.
        try:
            CampaignQuotaService.consume_email_quota(host, count=len(contacts))
        except QuotaExceededError as e:
            raise CampaignError(e.message, e.status)

        sender_name  = data.get("sender_name")  or event.organizer_display_name
        sender_email = data.get("sender_email") or event.public_email

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
            with transaction.atomic():
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

                brevo.sync_contacts_to_list(list_id, contacts)

                brevo_campaign_id = brevo.create_email_campaign(
                    name         = campaign.campaign_name,
                    subject      = campaign.subject,
                    html_content = campaign.html_content,
                    sender_name  = sender_name,
                    sender_email = sender_email,
                    list_id      = list_id,
                )
                brevo.send_email_campaign(brevo_campaign_id)

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
            campaign.status = "failed"
            campaign.save(update_fields=["status"])
            raise CampaignError("Failed to send campaign. Please try again.", 500)

        return campaign

    # ── Single Email Send ─────────────────────────────────────────────────────

    @staticmethod
    def send_single_email(host, data):
        """
        Consumes 1 email quota before sending.
        Blocked immediately if quota is 0.
        """
        from host.services.campaign_quota_service import CampaignQuotaService, QuotaExceededError

        try:
            CampaignQuotaService.consume_email_quota(host, count=1)
        except QuotaExceededError as e:
            raise CampaignError(e.message, e.status)

        try:
            brevo.send_transactional_email(
                to_email     = data["recipient_email"],
                subject      = data["subject"],
                html_content = data["html_content"],
                sender_name  = data.get("sender_name", "QavTix"),
                sender_email = data.get("sender_email", "savieztech@gmail.com"),
            )
        except Exception as exc:
            logger.exception("Single email send failed: %s", exc)
            # Quota was already consumed — log it but don't refund
            # (refunding opens race conditions and is complex to handle safely)
            raise CampaignError("Failed to send email. Please try again.", 500)

    # ── Single SMS Send ───────────────────────────────────────────────────────

    @staticmethod
    def send_single_sms(host, data):
        """
        Consumes 1 SMS quota before sending.
        Blocked immediately if quota is 0.
        """
        from host.services.campaign_quota_service import CampaignQuotaService, QuotaExceededError

        try:
            CampaignQuotaService.consume_sms_quota(host, count=1)
        except QuotaExceededError as e:
            raise CampaignError(e.message, e.status)

        sender = data.get("sender_name") or "QavTix"
        sender = "".join(filter(str.isalnum, sender))[:11]

        try:
            brevo.send_transactional_sms(
                recipient = data["recipient_phone"],
                content   = data["message"],
                sender    = sender,
            )
        except Exception as exc:
            logger.exception("SMS send failed: %s", exc)
            raise CampaignError(f"Failed to send SMS. Please try again.", 500)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_contact_list(event) -> list[dict]:
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


class CampaignError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)