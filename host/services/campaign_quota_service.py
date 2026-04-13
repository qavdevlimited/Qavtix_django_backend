# host/services/campaign_quota_service.py

import logging
from django.db import transaction

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    def __init__(self, message, remaining, limit, status=400):
        self.message   = message
        self.remaining = remaining
        self.limit     = limit
        self.status    = status
        super().__init__(message)


class CampaignQuotaService:
    """
    Single source of truth for campaign send quota enforcement.

    Rules:
    - Quota is tied to the active subscription — no rollover across periods.
    - When a new subscription becomes active, a new CampaignUsage row is created.
    - Cancelled subscriptions retain access until expiry but share the same usage row.
    - Free plan = 0 limit = no sends allowed.
    - None limit = unlimited (enterprise feature future-proofing).
    """

    # ── Get or create usage row for current subscription ─────────────────────

    @staticmethod
    def _get_or_create_usage(host):
        """
        Returns the CampaignUsage row for the host's current active subscription.
        Creates one if it doesn't exist yet.
        """
        from host.models import CampaignUsage

        # Get the active/cancelled subscription (same logic as get_host_plan_slug)
        from django.utils import timezone
        sub = (
            host.subscriptions
            .filter(status__in=["active", "cancelled"])
            .order_by("-started_at")
            .first()
        )

        if not sub:
            # Free plan — no subscription row — use a host-only usage row
            usage, _ = CampaignUsage.objects.get_or_create(
                host=host,
                subscription=None,
                defaults={"email_sends_used": 0, "sms_sends_used": 0},
            )
            return usage

        usage, _ = CampaignUsage.objects.get_or_create(
            host=host,
            subscription=sub,
            defaults={"email_sends_used": 0, "sms_sends_used": 0},
        )
        return usage

    # ── Check remaining quota without consuming ───────────────────────────────

    @staticmethod
    def get_email_quota(host):
        """
        Returns dict with limit, used, remaining for email sends.
        remaining = None means unlimited.
        """
        from host.plan_limits import get_host_plan_slug, get_limit

        plan_slug = get_host_plan_slug(host)
        limit     = get_limit(plan_slug, "email_campaign_limit")
        usage     = CampaignQuotaService._get_or_create_usage(host)

        if limit is None:
            return {"limit": None, "used": usage.email_sends_used, "remaining": None}

        remaining = max(0, limit - usage.email_sends_used)
        return {"limit": limit, "used": usage.email_sends_used, "remaining": remaining}

    @staticmethod
    def get_sms_quota(host):
        """
        Returns dict with limit, used, remaining for SMS sends.
        remaining = None means unlimited.
        """
        from host.plan_limits import get_host_plan_slug, get_limit

        plan_slug = get_host_plan_slug(host)
        limit     = get_limit(plan_slug, "sms_campaign_limit")
        usage     = CampaignQuotaService._get_or_create_usage(host)

        if limit is None:
            return {"limit": None, "used": usage.sms_sends_used, "remaining": None}

        remaining = max(0, limit - usage.sms_sends_used)
        return {"limit": limit, "used": usage.sms_sends_used, "remaining": remaining}

    # ── Check and consume quota atomically ────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def consume_email_quota(host, count=1):
        """
        Validates that host has enough email quota, then consumes it atomically.
        Raises QuotaExceededError if not enough quota.

        count = number of sends to consume (1 for single, N for campaign)
        """
        from host.models import CampaignUsage
        from host.plan_limits import get_host_plan_slug, get_limit, has_feature

        plan_slug = get_host_plan_slug(host)

        # Check feature access first
        if not has_feature(plan_slug, "email_campaigns"):
            raise QuotaExceededError(
                "Email campaigns are not available on your current plan. Upgrade to Pro.",
                remaining=0,
                limit=0,
                status=403,
            )

        limit = get_limit(plan_slug, "email_campaign_limit")

        # None = unlimited — skip quota check
        if limit is None:
            usage = CampaignQuotaService._get_or_create_usage(host)
            CampaignUsage.objects.filter(id=usage.id).update(
                email_sends_used=usage.email_sends_used + count
            )
            return

        # Row-level lock to prevent race conditions
        usage = (
            CampaignUsage.objects
            .select_for_update()
            .filter(host=host)
            .order_by("-created_at")
            .first()
        )
        if not usage:
            usage = CampaignQuotaService._get_or_create_usage(host)
            usage = CampaignUsage.objects.select_for_update().get(id=usage.id)

        remaining = max(0, limit - usage.email_sends_used)

        if count > remaining:
            raise QuotaExceededError(
                f"Not enough email quota. You need {count} send(s) but only have "
                f"{remaining} remaining out of {limit} for this subscription period.",
                remaining=remaining,
                limit=limit,
                status=400,
            )

        usage.email_sends_used += count
        usage.save(update_fields=["email_sends_used", "updated_at"])

        logger.info(
            f"Email quota consumed: host={host.id}, count={count}, "
            f"used={usage.email_sends_used}/{limit}"
        )

    @staticmethod
    @transaction.atomic
    def consume_sms_quota(host, count=1):
        """
        Validates that host has enough SMS quota, then consumes it atomically.
        Raises QuotaExceededError if not enough quota.
        """
        from host.models import CampaignUsage
        from host.plan_limits import get_host_plan_slug, get_limit, has_feature

        plan_slug = get_host_plan_slug(host)

        # Check feature access first
        if not has_feature(plan_slug, "sms_campaigns"):
            raise QuotaExceededError(
                "SMS campaigns are not available on your current plan. Upgrade to Pro.",
                remaining=0,
                limit=0,
                status=403,
            )

        limit = get_limit(plan_slug, "sms_campaign_limit")

        # None = unlimited
        if limit is None:
            usage = CampaignQuotaService._get_or_create_usage(host)
            CampaignUsage.objects.filter(id=usage.id).update(
                sms_sends_used=usage.sms_sends_used + count
            )
            return

        # Row-level lock
        usage = (
            CampaignUsage.objects
            .select_for_update()
            .filter(host=host)
            .order_by("-created_at")
            .first()
        )
        if not usage:
            usage = CampaignQuotaService._get_or_create_usage(host)
            usage = CampaignUsage.objects.select_for_update().get(id=usage.id)

        remaining = max(0, limit - usage.sms_sends_used)

        if count > remaining:
            raise QuotaExceededError(
                f"Not enough SMS quota. You need {count} send(s) but only have "
                f"{remaining} remaining out of {limit} for this subscription period.",
                remaining=remaining,
                limit=limit,
                status=400,
            )

        usage.sms_sends_used += count
        usage.save(update_fields=["sms_sends_used", "updated_at"])

        logger.info(
            f"SMS quota consumed: host={host.id}, count={count}, "
            f"used={usage.sms_sends_used}/{limit}"
        )