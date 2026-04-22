"""
administrator/service/customer_service.py

Customer/Attendee management with role-based access control.
"""

import logging
from decimal import Decimal
from django.db.models import Count, Sum, Avg, Q, Min, Max
from django.utils import timezone
from django.contrib.auth import get_user_model
from administrator.rolecontrol import RoleControlService

logger = logging.getLogger(__name__)
User = get_user_model()


class AdminCustomerCardService:
    """Cards for the admin customer dashboard with role-based filtering."""

    @staticmethod
    def get_cards(user=None, date_range=None):
        """Get customer cards. Normal admins see their country only."""
        from attendee.models import Attendee
        from transactions.models import Order

        now         = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        attendee_qs = Attendee.objects.all()
        order_qs    = Order.objects.filter(status="completed")

        # Apply role control filtering
        if user:
            attendee_qs = RoleControlService.filter_by_admin(user, attendee_qs, "attendee")
            order_qs = RoleControlService.filter_by_admin(user, order_qs, "order")

        # Apply date range filter
        if date_range == "day":
            since = now - timezone.timedelta(days=1)
        elif date_range == "week":
            since = now - timezone.timedelta(weeks=1)
        elif date_range == "month":
            since = month_start
        elif date_range == "year":
            since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            since = month_start

        # Total customers
        total_customers = attendee_qs.count()

        # New this period
        new_this_period = attendee_qs.filter(registration_date__gte=since).count()

        # Repeat buyers
        repeat_buyers = (
            order_qs
            .values("user")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
            .count()
        )

        # Average spend
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
    """Paginated attendee list with role-based access control."""

    @staticmethod
    def get_customers(
        user=None,
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
        """Get customer list. Normal admins see their country only."""
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

        # ── Apply role control filtering FIRST ──────────────────────────────
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "attendee")

        # ── Status filter ──────────────────────────────────────────────────
        if status == "active":
            qs = qs.filter(user__is_active=True)
        elif status in ("suspended", "banned"):
            qs = qs.filter(user__is_active=False)
        elif status == "flagged":
            flagged_ids = AdminCustomerListService._get_flagged_user_ids()
            qs = qs.filter(user_id__in=flagged_ids)

        # ── Location filters ───────────────────────────────────────────────
        # For normal admins, country filter is already applied via role control
        # But respect user-provided country filter if they ask
        if country:
            qs = qs.filter(country__iexact=country)
        if state:
            qs = qs.filter(state__iexact=state)
        if city:
            qs = qs.filter(city__iexact=city)

        # ── Spend range ────────────────────────────────────────────────────
        if min_spend is not None:
            qs = qs.filter(total_spend__gte=min_spend)
        if max_spend is not None:
            qs = qs.filter(total_spend__lte=max_spend)

        # ── Date joined range ──────────────────────────────────────────────
        if date_joined_from:
            qs = qs.filter(registration_date__date__gte=date_joined_from)
        if date_joined_to:
            qs = qs.filter(registration_date__date__lte=date_joined_to)

        # ── Search ─────────────────────────────────────────────────────────
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