# administrator/service/customer_service.py

import logging
from decimal import Decimal
from django.db.models import Count, Sum, Avg, Q, Min, Max
from django.utils import timezone
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


class AdminCustomerCardService:
    """
    Cards for the admin customer dashboard.
    Filterable by date range: day | week | month | year
    """

    @staticmethod
    def get_cards(date_range=None):
        from attendee.models import Attendee
        from transactions.models import Order

        now         = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Base attendee queryset
        attendee_qs = Attendee.objects.all()
        order_qs    = Order.objects.filter(status="completed")

        # Apply date range filter for new customers card
        if date_range == "day":
            since = now - timezone.timedelta(days=1)
        elif date_range == "week":
            since = now - timezone.timedelta(weeks=1)
        elif date_range == "month":
            since = month_start
        elif date_range == "year":
            since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            since = month_start  # default to month

        # Total customers — all attendees
        total_customers = attendee_qs.count()

        # New this period
        new_this_period = Attendee.objects.filter(
            registration_date__gte=since
        ).count()

        # Repeat buyers — users with more than 1 completed order
        repeat_buyers = (
            order_qs
            .values("user")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
            .count()
        )

        # Average spend per customer
        per_user = (
            order_qs
            .values("user")
            .annotate(spent=Sum("total_amount"))
        )
        if per_user.exists():
            total_spent = sum(r["spent"] or 0 for r in per_user)
            avg_spend   = round(Decimal(str(total_spent)) / per_user.count(), 2)
        else:
            avg_spend = Decimal("0.00")

        return {
            "total_customers":  total_customers,
            "new_this_period":  new_this_period,
            "repeat_buyers":    repeat_buyers,
            "average_spend":    avg_spend,
        }


class AdminCustomerListService:
    """
    Paginated attendee list for admin.
    Filterable by status, location, spend range, date joined.
    No N+1 — uses annotations and select_related.
    """

    @staticmethod
    def get_customers(
        status=None,
        country=None,
        state=None,
        city=None,
        min_spend=None,
        max_spend=None,
        date_joined_from=None,
        date_joined_to=None,
        search=None,
    ):
        from attendee.models import Attendee
        from transactions.models import Order
        from django.db.models import OuterRef, Subquery, DecimalField

        # Subquery for total spend per user
        spend_subquery = (
            Order.objects
            .filter(user=OuterRef("user"), status="completed")
            .values("user")
            .annotate(total=Sum("total_amount"))
            .values("total")
        )

        # Subquery for ticket count per user
        ticket_subquery = (
            Order.objects
            .filter(user=OuterRef("user"), status="completed")
            .values("user")
            .annotate(cnt=Count("id"))
            .values("cnt")
        )

        qs = (
            Attendee.objects
            .select_related("user")
            .annotate(
                total_spend=Subquery(
                    spend_subquery,
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                ),
                tickets_bought=Subquery(
                    ticket_subquery,
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                ),
            )
        )

        # ── Status filter ──────────────────────────────────────────────────────
        # Django's is_active: True=active, False=suspended/banned
        # We track flagged via a separate field — see FlaggedUser model
        if status == "active":
            qs = qs.filter(user__is_active=True)
        elif status in ("suspended", "banned"):
            qs = qs.filter(user__is_active=False)
        elif status == "flagged":
            flagged_ids = AdminCustomerListService._get_flagged_user_ids()
            qs = qs.filter(user_id__in=flagged_ids)

        # ── Location filters ───────────────────────────────────────────────────
        if country:
            qs = qs.filter(country__iexact=country)
        if state:
            qs = qs.filter(state__iexact=state)
        if city:
            qs = qs.filter(city__iexact=city)

        # ── Spend range ────────────────────────────────────────────────────────
        if min_spend is not None:
            qs = qs.filter(total_spend__gte=min_spend)
        if max_spend is not None:
            qs = qs.filter(total_spend__lte=max_spend)

        # ── Date joined range ─────────────────────────────────────────────────
        if date_joined_from:
            qs = qs.filter(registration_date__date__gte=date_joined_from)
        if date_joined_to:
            qs = qs.filter(registration_date__date__lte=date_joined_to)

        # ── Search ────────────────────────────────────────────────────────────
        if search:
            qs = qs.filter(
                Q(full_name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(phone_number__icontains=search)
            )

        return qs.order_by("-registration_date")

    @staticmethod
    def _get_flagged_user_ids():
        """Returns user IDs that have been flagged by the system."""
        from administrator.models import FlaggedUser
        return FlaggedUser.objects.filter(
            is_active=True
        ).values_list("user_id", flat=True)

    @staticmethod
    def get_customer_status(attendee):
        """Determines display status for an attendee."""
        from administrator.models import FlaggedUser

        if not attendee.user.is_active:
            return "suspended"

        is_flagged = FlaggedUser.objects.filter(
            user=attendee.user, is_active=True
        ).exists()
        if is_flagged:
            return "flagged"

        return "active"