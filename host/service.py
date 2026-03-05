from decimal import Decimal

from django.db.models import Count, Sum, Q
from django.utils import timezone

from events.models import Ticket, PromoCode
from attendee.models import AffiliateLink          # adjust to your path
from transactions.models import Order


# ── Promo Codes ────────────────────────────────────────────────────────────────

class PromoCodeService:

    @staticmethod
    def get_host_promo_codes(host, event_id=None, status=None, search=None):
        today = timezone.now().date()

        qs = (
            PromoCode.objects
            .select_related(
                "ticket",
                "ticket__event",
                "ticket__event__category",
            )
            .prefetch_related("ticket__event__media")
            .filter(ticket__event__host=host)
        )

        if event_id:
            qs = qs.filter(ticket__event_id=event_id)
        if status == "active":
            qs = qs.filter(valid_till__gte=today)
        elif status == "ended":
            qs = qs.filter(valid_till__lt=today)
        if search:
            qs = qs.filter(code__icontains=search)

        promo_codes_in_qs = list(qs.values_list("code", flat=True))
        usage_map = PromoCodeService._usage_map(host, promo_codes_in_qs)

        promo_list = list(qs)
        for promo in promo_list:
            stats = usage_map.get(promo.code, {})
            promo.usage_count    = stats.get("usage_count", 0)
            promo.revenue_impact = stats.get("revenue_impact", Decimal("0.00"))

        return promo_list

    @staticmethod
    def _usage_map(host, codes):
        """
        Revenue impact explained
        ────────────────────────
        When a promo code is applied at checkout, _apply_promo() calculates the
        discount and _create_order() stores:
          - Order.discount       = the actual money subtracted from the subtotal
          - Order.metadata       = {"promo_code": "<code>", ...}

        So for each code we query completed orders where metadata["promo_code"]
        matches, then:
          usage_count    = COUNT(order.id)         — how many times the code was used
          revenue_impact = SUM(order.discount)     — total money discounted via this code

        This is accurate because Order.discount is set per-order at the moment
        the promo is applied, so it captures the real discount even if the
        discount_percentage changes later.
        """
        rows = (
            Order.objects
            .filter(
                event__host=host,
                status="completed",
                metadata__promo_code__in=codes,
            )
            .values("metadata__promo_code")
            .annotate(
                usage_count=Count("id"),
                revenue_impact=Sum("discount"),
            )
        )
        return {
            row["metadata__promo_code"]: {
                "usage_count":    row["usage_count"],
                "revenue_impact": row["revenue_impact"] or Decimal("0.00"),
            }
            for row in rows
        }

    @staticmethod
    def create_promo_code(host, data):
        """
        Create the promo code for every ticket under the event in one go.
        Raises PromoCodeError if:
          - the event doesn't belong to this host
          - the event has no tickets
          - the code already exists on any ticket in that event
        """
        from events.models import Event

        # Verify event ownership
        try:
            event = Event.objects.get(id=data["event_id"], host=host)
        except Event.DoesNotExist:
            raise PromoCodeError(
                "Event not found or does not belong to you.", 404
            )

        tickets = list(Ticket.objects.filter(event=event))
        if not tickets:
            raise PromoCodeError(
                "This event has no tickets to attach a promo code to.", 400
            )

        # Prevent duplicate code on any ticket in this event
        if PromoCode.objects.filter(
            ticket__event=event, code=data["code"]
        ).exists():
            raise PromoCodeError(
                "A promo code with this code already exists for this event.", 400
            )

        # Bulk-create one PromoCode per ticket
        promos = PromoCode.objects.bulk_create([
            PromoCode(
                ticket=ticket,
                code=data["code"],
                discount_percentage=data["discount_percentage"],
                maximum_users=data["usage_limit"],
                valid_till=data["valid_until"],
            )
            for ticket in tickets
        ])

        return event, promos


class PromoCodeError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)


# ── Affiliates ─────────────────────────────────────────────────────────────────

class AffiliateService:

    @staticmethod
    def get_host_affiliates(host, event_id=None, search=None):
        """
        Returns (cards_dict, ranked_affiliate_list).

        Rank is determined by sales descending — the affiliate with the most
        sales gets rank 1. Ties share the same rank.
        """
        qs = (
            AffiliateLink.objects
            .select_related(
                "user",
                "user__attendee_profile",   # ← full_name lives here
                "event",
                "event__category",
            )
            .prefetch_related("event__media", "earnings")
            .filter(event__host=host)
            .annotate(
                total_earnings=Sum(
                    "earnings__earning",
                    filter=Q(earnings__status="succeeded"),
                )
            )
        )

        if event_id:
            qs = qs.filter(event_id=event_id)

        if search:
            # Search against Attendee.full_name and user.email
            qs = qs.filter(
                Q(user__attendee_profile__full_name__icontains=search) |
                Q(user__email__icontains=search)
            )

        cards = AffiliateService._cards(qs)

        # Materialise and rank by sales descending
        affiliate_list = list(qs.order_by("-sales"))
        AffiliateService._attach_ranks(affiliate_list)

        # Normalise None earnings to Decimal zero
        for link in affiliate_list:
            if link.total_earnings is None:
                link.total_earnings = Decimal("0.00")

        return cards, affiliate_list

    @staticmethod
    def _attach_ranks(affiliate_list):
        """
        Dense rank by sales descending.
        e.g. sales [10, 10, 7, 3] → ranks [1, 1, 2, 3]
        """
        rank = 1
        for i, link in enumerate(affiliate_list):
            if i == 0:
                link.rank = 1
            else:
                if link.sales < affiliate_list[i - 1].sales:
                    rank = i + 1
                link.rank = rank

    @staticmethod
    def _cards(qs):
        from django.utils import timezone

        now         = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ── total affiliates in the filtered scope ────────────────────────────
        total_affiliates = qs.count()

        # ── new this month: affiliate links created in the current calendar month
        # Uses the same filtered qs so event/search filters still apply.
        new_this_month = qs.filter(created_at__gte=month_start).count()

        # ── total tickets sold: sum of AffiliateLink.sales across filtered links
        # AffiliateLink.sales is incremented by your payment webhook each time
        # a ticket is purchased via that affiliate link.
        agg = qs.aggregate(
            tickets_sold=Sum("sales"),
            commission_paid=Sum(
                "earnings__earning",
                filter=Q(earnings__status="succeeded"),
            ),
        )

        return {
            "total_affiliates":      total_affiliates,
            "new_this_month":        new_this_month,
            "total_tickets_sold":    agg["tickets_sold"]    or 0,
            "total_commission_paid": agg["commission_paid"] or Decimal("0.00"),
        }
