# administrator/service/event_service.py

import logging
from decimal import Decimal
from django.db.models import (
    Count, Sum, Q, F, OuterRef, Subquery,
    IntegerField, DecimalField
)
from django.db.models.functions import TruncMonth, TruncDay
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


def _get_since(date_range):
    now = timezone.now()
    if date_range == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    elif date_range == "week":
        return now - timedelta(weeks=1), now
    elif date_range == "year":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), now
    else:  # month default
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now


# ─────────────────────────────────────────────────────────────────────────────
# Event Cards
# ─────────────────────────────────────────────────────────────────────────────

class AdminEventCardService:

    @staticmethod
    def get_cards(date_range="month"):
        from events.models import Event
        from django.utils import timezone

        now          = timezone.now()
        since, until = _get_since(date_range)

        base = Event.objects.filter(created_at__gte=since, created_at__lt=until)

        # Live — currently running
        live = Event.objects.filter(
        ).count()

        # Suspended — is_active=False or status=banned
        suspended = Event.objects.filter(
            Q(status="banned") | Q(status="cancelled")
        ).filter(created_at__gte=since).count()

        # Ended
        ended = Event.objects.filter(
            Q(status="ended") | Q(end_datetime__lt=now, status="active")
        ).filter(created_at__gte=since).count()

        # Sold out
        sold_out = Event.objects.filter(
            status="sold-out",
            created_at__gte=since,
        ).count()

        return {
            "live":      live,
            "suspended": suspended,
            "ended":     ended,
            "sold_out":  sold_out,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Event List
# ─────────────────────────────────────────────────────────────────────────────

class AdminEventListService:

    @staticmethod
    def get_events(
        status=None,
        category=None,
        host_id=None,
        city=None,
        state=None,
        country=None,
        date_from=None,
        date_to=None,
        performance=None,
        search=None,
        event_state=None,   # live | ended | cancelled | suspended
    ):
        from events.models import Event
        from transactions.models import OrderTicket,Order

        # Subquery for tickets sold — avoids cross-join inflation
        tickets_sold_sq = Subquery(
            OrderTicket.objects
            .filter(order__event=OuterRef("pk"), order__status="completed")
            .values("order__event")
            .annotate(total=Sum("quantity"))
            .values("total"),
            output_field=IntegerField(),
        )

        # Subquery for revenue — clean, no fan-out
        revenue_sq = Subquery(
                    Order.objects
                    .filter(
                        event=OuterRef("pk"),
                        status="completed"
                    )
                    .values("event")
                    .annotate(total=Sum("total_amount"))
                    .values("total"),
                    output_field=DecimalField(max_digits=10, decimal_places=2)
                )

        qs = (
            Event.objects
            .select_related("category", "host", "host__user", "event_location")
            .prefetch_related("media", "tickets")
            .annotate(
                tickets_sold  = tickets_sold_sq,
                total_listed  = Sum("tickets__quantity"),
                revenue       = revenue_sq,
            )
        )

        now = timezone.now()

        # Event state filter
        if event_state == "live":
            qs = qs.filter(status="active", start_datetime__lte=now, end_datetime__gte=now)
        elif event_state == "ended":
            qs = qs.filter(Q(status="ended") | Q(end_datetime__lt=now))
        elif event_state == "cancelled":
            qs = qs.filter(status="cancelled")
        elif event_state == "suspended":
            qs = qs.filter(status="banned")

        if status:
            qs = qs.filter(status__iexact=status)
        if category:
            qs = qs.filter(category_id=category)
        if host_id:
            qs = qs.filter(host_id=host_id)
        if city:
            qs = qs.filter(event_location__city__iexact=city)
        if state:
            qs = qs.filter(event_location__state__iexact=state)
        if country:
            qs = qs.filter(event_location__country__iexact=country)
        if date_from:
            qs = qs.filter(start_datetime__date__gte=date_from)
        if date_to:
            qs = qs.filter(start_datetime__date__lte=date_to)
        if search:
            qs = qs.filter(
                Q(title__icontains=search) |
                Q(host__business_name__icontains=search) |
                Q(host__full_name__icontains=search)
            )

        if performance == "high":
            qs = qs.order_by(F("revenue").desc(nulls_last=True))
        elif performance == "low":
            qs = qs.order_by(F("revenue").asc(nulls_last=True))
        else:
            qs = qs.order_by("-created_at")

        return qs


# ─────────────────────────────────────────────────────────────────────────────
# Event Attendee List
# ─────────────────────────────────────────────────────────────────────────────

class AdminEventAttendeeService:

    @staticmethod
    def get_attendees(
        event_id,
        ticket_type_id=None,
        min_amount=None,
        max_amount=None,
        date_from=None,
        date_to=None,
        status=None,
    ):
        from transactions.models import IssuedTicket

        qs = (
            IssuedTicket.objects
            .select_related(
                "owner",
                "owner__attendee_profile",
                "order",
                "order_ticket",
                "order_ticket__ticket",
            )
            .filter(event_id=event_id)
            .exclude(status="reserved")
        )

        if ticket_type_id:
            qs = qs.filter(order_ticket__ticket_id=ticket_type_id)
        if status:
            qs = qs.filter(status__iexact=status)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        if min_amount is not None:
            qs = qs.filter(order__total_amount__gte=min_amount)
        if max_amount is not None:
            qs = qs.filter(order__total_amount__lte=max_amount)

        return qs.order_by("-created_at")

    @staticmethod
    def get_ticket_types(event_id):
        """Returns all ticket types for an event — used by FE for filter dropdown."""
        from events.models import Ticket
        return (
            Ticket.objects
            .filter(event_id=event_id)
            .values("id", "ticket_type", "price", "quantity", "sold_count")
        )


# ─────────────────────────────────────────────────────────────────────────────
# Event Actions
# ─────────────────────────────────────────────────────────────────────────────

class AdminEventActionService:

    @staticmethod
    def suspend_event(event_id):
        """Toggles event between active and banned."""
        from events.models import Event
        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return False, "Event not found."

        if event.status == "banned":
            event.status = "active"
            event.save(update_fields=["status"])
            return True, f'"{event.title}" has been unsuspended.'
        else:
            event.status = "banned"
            event.save(update_fields=["status"])
            return True, f'"{event.title}" has been suspended.'

    @staticmethod
    def delete_event(event_id):
        """Hard deletes an event. Use with caution."""
        from events.models import Event
        try:
            event = Event.objects.get(id=event_id)
            title = event.title
            event.delete()
            return True, f'"{title}" has been permanently deleted.'
        except Event.DoesNotExist:
            return False, "Event not found."

    @staticmethod
    def feature_event(event_id, plan_slug, admin_user):
        """
        Admin assigns a featured plan to an event at no charge.
        Creates FeaturedEvent with payment_method='admin_assignment'.
        End date is auto-calculated from plan duration.
        """
        from events.models import Event
        from transactions.models import FeaturedEvent, FeaturedPlan
        from django.utils import timezone

        try:
            featured = FeaturedEvent.objects.get(event_id=event_id, status="active")
            return False, f'"{featured.event.title}" is already featured under {featured.metadata.get("plan_name", "a plan")} until {featured.end_date.strftime("%d %b %Y")}. Please cancel the existing featured slot before assigning a new one.', 409
        except FeaturedEvent.DoesNotExist:
            pass  # No active featured slot, proceed with assignment

        try:
            event = Event.objects.select_related("host__user").get(id=event_id)
        except Event.DoesNotExist:
            return False, "Event not found.", None

        try:
            plan = FeaturedPlan.objects.get(slug=plan_slug, is_active=True)
        except FeaturedPlan.DoesNotExist:
            return False, f"Featured plan '{plan_slug}' not found.", None

        # Cancel any existing active featured slot for this event
        FeaturedEvent.objects.filter(
            event=event, status="active"
        ).update(status="cancelled")

        now      = timezone.now()
        end_date = now + timezone.timedelta(days=plan.duration_days)

        featured = FeaturedEvent.objects.create(
            event          = event,
            user           = event.host.user,
            end_date       = end_date,
            payment_amount = plan.price,
            payment_method = "admin_assignment",
            status         = "active",
            metadata       = {
                "plan_slug":     plan_slug,
                "plan_name":     plan.name,
                "duration_days": plan.duration_days,
                "assigned_by":   admin_user.email,
                "assigned_at":   now.isoformat(),
            },
        )

        return True, f'"{event.title}" is now featured under {plan.name} plan until {end_date.strftime("%d %b %Y")}.', featured