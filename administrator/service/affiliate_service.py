# administrator/service/affiliate_service.py

import logging
from decimal import Decimal
from django.db.models import Count, Sum, Q, Max, F
from django.utils import timezone

logger = logging.getLogger(__name__)


from administrator.rolecontrol import RoleControlService

class AdminAffiliateCardService:

    @staticmethod
    def get_cards(user=None, date_range=None):
        from attendee.models import AffiliateLink, AffliateEarnings

        now = timezone.now()

        if date_range == "day":
            since = now - timezone.timedelta(days=1)
        elif date_range == "week":
            since = now - timezone.timedelta(weeks=1)
        elif date_range == "year":
            since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ── APPLY RBAC HERE ───────────────────────────────────────────────
        base_qs = AffiliateLink.objects.all()
        earnings_qs = AffliateEarnings.objects.filter(
            earning_type="affiliate",
            status="paid",
        )

        if user:
            base_qs = RoleControlService.filter_by_admin(user, base_qs, "affiliatelink")
            earnings_qs = RoleControlService.filter_by_admin(user, earnings_qs, "affliateearnings")

        period_qs = base_qs.filter(created_at__gte=since)

        # ── Affiliates ────────────────────────────────────────────────────
        total_affiliates = base_qs.count()

        prev_since = since - (now - since)

        prev_count = base_qs.filter(
            created_at__gte=prev_since,
            created_at__lt=since,
        ).count()

        period_count = period_qs.count()
        affiliate_growth = _pct_change(period_count, prev_count)

        # ── Clicks ────────────────────────────────────────────────────────
        total_clicks = base_qs.aggregate(t=Sum("clicks"))["t"] or 0
        period_clicks = period_qs.aggregate(t=Sum("clicks"))["t"] or 0

        prev_clicks = base_qs.filter(
            created_at__gte=prev_since,
            created_at__lt=since
        ).aggregate(t=Sum("clicks"))["t"] or 0

        clicks_growth = _pct_change(period_clicks, prev_clicks)

        # ── Conversion ────────────────────────────────────────────────────
        total_sales = base_qs.aggregate(t=Sum("sales"))["t"] or 0

        conversion_rate = (
            round((total_sales / total_clicks) * 100, 2)
            if total_clicks else 0.0
        )

        prev_sales = base_qs.filter(
            created_at__gte=prev_since,
            created_at__lt=since
        ).aggregate(t=Sum("sales"))["t"] or 0

        prev_conversion_rate = (
            round((prev_sales / prev_clicks) * 100, 2)
            if prev_clicks else 0.0
        )

        conversion_rate_growth = _pct_change(conversion_rate, prev_conversion_rate)

        # ── Commission ────────────────────────────────────────────────────
        total_commission = earnings_qs.aggregate(t=Sum("earning"))["t"] or Decimal("0.00")

        period_commission = earnings_qs.filter(
            created_at__gte=since,
        ).aggregate(t=Sum("earning"))["t"] or Decimal("0.00")

        prev_commission = earnings_qs.filter(
            created_at__gte=prev_since,
            created_at__lt=since,
        ).aggregate(t=Sum("earning"))["t"] or Decimal("0.00")

        commission_growth = _pct_change(
            float(period_commission),
            float(prev_commission)
        )

        return {
            "total_affiliates": total_affiliates,
            "affiliate_growth": affiliate_growth,
            "total_clicks": total_clicks,
            "clicks_growth": clicks_growth,
            "conversion_rate": conversion_rate,
            "conversion_rate_growth": conversion_rate_growth,
            "total_commission": total_commission,
            "commission_growth": commission_growth,
        }


class AdminAffiliateListService:

    @staticmethod
    def get_affiliates(user=None, last_activity_from=None, last_activity_to=None, search=None):
        from attendee.models import AffiliateLink

        qs = (
            AffiliateLink.objects
            .select_related(
                "user",
                "user__attendee_profile",
                "event",
            )
            .annotate(
                total_commission=Sum(
                    "earnings__earning",
                    filter=Q(earnings__earning_type="affiliate"),
                ),
                last_activity=Max("earnings__created_at"),
            )
            .order_by("-last_activity")
        )

        # ── APPLY RBAC FIRST ──────────────────────────────────────────────
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "affiliatelink")

        # ── Filters ───────────────────────────────────────────────────────
        if last_activity_from:
            qs = qs.filter(updated_at__date__gte=last_activity_from)

        if last_activity_to:
            qs = qs.filter(updated_at__date__lte=last_activity_to)

        if search:
            qs = qs.filter(
                Q(user__attendee_profile__full_name__icontains=search) |
                Q(user__email__icontains=search)
            )

        return qs


def _pct_change(current, previous):
    if not previous:
        return 100.0 if current else 0.0
    return round(((current - previous) / previous) * 100, 2)