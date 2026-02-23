from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Sum, Count,Prefetch
from django.http import Http404
from transactions.models import Order,IssuedTicket
from .filters import TicketDashboardFilter
from .serializers import TicketDashboardSerializer
from attendee.models import AffliateEarnings
from events.models import EventMedia


class TicketDashboardView(generics.ListAPIView):
    serializer_class = TicketDashboardSerializer
    permission_classes = [permissions.IsAuthenticated]

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    filterset_class = TicketDashboardFilter
    search_fields = ["event__title"]
    ordering_fields = ["created_at", "event__start_datetime"]
    ordering = ["-created_at"]

    def get_queryset(self):
        # Prefetch only featured media
        featured_media = EventMedia.objects.filter(is_featured=True)

        return (
            IssuedTicket.objects
            .filter(owner=self.request.user)
            .select_related(
                "event",
                "order",
                "owner",
                "event__category"  # make sure Event.category exists
            )
            .prefetch_related(
                Prefetch("event__media", queryset=featured_media)
            )
            .order_by("-created_at")
        )

    def list(self, request, *args, **kwargs):
        user = request.user
        now = timezone.now()

        start_week = now - timezone.timedelta(days=now.weekday())  # Monday
        start_month = now.replace(day=1)

        if not hasattr(user, "attendee_profile"):
            raise Http404("You are not an attendee.")

        attendee = user.attendee_profile

        # TOTAL SPENT
        completed_orders = Order.objects.filter(
            user=user,
            status="completed"
        )
        
        total_spent = completed_orders.aggregate(
            total=Sum("total_amount")
        )["total"] or 0

        spent_this_month = Order.objects.filter(
            user=user,
            status="completed",
            created_at__gte=start_month
        ).aggregate(total=Sum("total_amount"))["total"] or 0


        # TOTAL TICKETS PURCHASED-
        total_tickets = completed_orders.aggregate(
            total=Sum("tickets__quantity")
        )["total"] or 0

        tickets_today = IssuedTicket.objects.filter(
            owner=user,
            created_at__date=now.date()
        ).count()


        
        # UPCOMING EVENTS
      
        # Get upcoming events queryset
        upcoming_events_qs = IssuedTicket.objects.filter(
            owner=request.user,
            event__start_datetime__gte=now
        ).order_by("event__start_datetime")  # keep it ordered by start time

        # Count
        upcoming_count = upcoming_events_qs.values("event").distinct().count()

        # First upcoming event
        next_event = upcoming_events_qs.first()
        next_event_datetime = next_event.event.start_datetime if next_event else None


        # TOTAL AFFILIATE EARNINGS
        total_earnings = AffliateEarnings.objects.filter(
            attendee=attendee
        ).aggregate(
            total=Sum("earning")
        )["total"] or 0

        earnings_this_week = AffliateEarnings.objects.filter(
            attendee__user=user,
            created_at__gte=start_week
        ).aggregate(total=Sum("earning"))["total"] or 0


        card_data = {
            "total_earnings": total_earnings,
            "earnings_this_week": earnings_this_week,
            "total_spent": total_spent,
            "spent_this_month": spent_this_month,
            "tickets_purchased": total_tickets,
            "tickets_today": tickets_today,
            "upcoming_events": upcoming_count,
            "next_event_datetime": next_event_datetime,
        }

        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        serializer = self.get_serializer(page or queryset, many=True)

        if page is not None:
            response = self.get_paginated_response(serializer.data)
            response.data["cards"] = card_data
            return response

        return api_response(
            message="Ticket dashboard fetched successfully",
            status_code=200,
            data={
                "cards": card_data,
                "table": serializer.data
            }
        )