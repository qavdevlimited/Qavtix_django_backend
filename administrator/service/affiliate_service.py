# administrator/service/affiliate_service.py

import logging
from decimal import Decimal
from django.db.models import Count, Sum, Q, Max, F
from django.utils import timezone

logger = logging.getLogger(__name__)


class AdminAffiliateCardService:
    """
    Cards for admin affiliate dashboard.
    Filterable by date range: day | week | month | year
    """

    @staticmethod
    def get_cards(date_range=None):
        from attendee.models import AffiliateLink, AffliateEarnings

        now = timezone.now()

        if date_range == "day":
            since = now - timezone.timedelta(days=1)
        elif date_range == "week":
            since = now - timezone.timedelta(weeks=1)
        elif date_range == "year":
            since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # month default
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        base_qs = AffiliateLink.objects.all()
        period_qs = base_qs.filter(created_at__gte=since)

        # Total affiliates — all time
        total_affiliates = base_qs.count()

        # Period affiliate count for growth % calculation
        prev_since = since - (now - since)
        prev_count = base_qs.filter(
            created_at__gte=prev_since,
            created_at__lt=since,
        ).count()
        period_count = period_qs.count()
        affiliate_growth = _pct_change(period_count, prev_count)

        # Total referral clicks — all time
        total_clicks = base_qs.aggregate(t=Sum("clicks"))["t"] or 0
        period_clicks = period_qs.aggregate(t=Sum("clicks"))["t"] or 0
        prev_clicks = base_qs.filter(
            created_at__gte=prev_since, created_at__lt=since
        ).aggregate(t=Sum("clicks"))["t"] or 0
        clicks_growth = _pct_change(period_clicks, prev_clicks)

        # Total conversions (sales)
        total_sales  = base_qs.aggregate(t=Sum("sales"))["t"] or 0
        total_clicks_all = base_qs.aggregate(t=Sum("clicks"))["t"] or 0
        conversion_rate  = (
            round((total_sales / total_clicks_all) * 100, 2)
            if total_clicks_all else 0.0
        )
        prev_sales  = base_qs.filter(
            created_at__gte=prev_since,
            created_at__lt=since
        ).aggregate(t=Sum("sales"))["t"] or 0

        prev_conversion_rate = (
            round((prev_sales / prev_clicks) * 100, 2)
            if prev_clicks > 0 else 0.0
        )

        # Conversion rate growth
        conversion_rate_growth = _pct_change(conversion_rate, prev_conversion_rate)

        # Total commission paid
        commission_agg = AffliateEarnings.objects.filter(
            earning_type="affiliate",
            status="paid",
        ).aggregate(t=Sum("earning"))
        total_commission = commission_agg["t"] or Decimal("0.00")

        period_commission = AffliateEarnings.objects.filter(
            earning_type="affiliate",
            status="paid",
            created_at__gte=since,
        ).aggregate(t=Sum("earning"))["t"] or Decimal("0.00")
        prev_commission = AffliateEarnings.objects.filter(
            earning_type="affiliate",
            status="paid",
            created_at__gte=prev_since,
            created_at__lt=since,
        ).aggregate(t=Sum("earning"))["t"] or Decimal("0.00")
        commission_growth = _pct_change(float(period_commission), float(prev_commission))

        return {
            "total_affiliates":    total_affiliates,
            "affiliate_growth":    affiliate_growth,
            "total_clicks":        total_clicks,
            "clicks_growth":       clicks_growth,
            "conversion_rate":     conversion_rate,
            "conversion_rate_growth": conversion_rate_growth,
            "total_commission":    total_commission,
            "commission_growth":   commission_growth,
        }


class AdminAffiliateListService:
    """
    Paginated affiliate list for admin.
    Filterable by last activity date range.
    No N+1 — single optimised query.
    """

    @staticmethod
    def get_affiliates(last_activity_from=None, last_activity_to=None, search=None):
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
                # Last activity = last time a sale or click happened
                last_activity=Max("earnings__created_at"),
            )
            .order_by("-last_activity")
        )

        # ── Last activity filter ───────────────────────────────────────────────
        if last_activity_from:
            qs = qs.filter(updated_at__date__gte=last_activity_from)

        if last_activity_to:
            qs = qs.filter(updated_at__date__lte=last_activity_to)

        # ── Search ────────────────────────────────────────────────────────────
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