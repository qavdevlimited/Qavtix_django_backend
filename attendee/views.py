from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Sum, Count,Prefetch
from django.http import Http404
from transactions.models import Order,IssuedTicket
from .filters import TicketDashboardFilter,FavoriteEventFilter
from .serializers import TicketDashboardSerializer,FavoriteEventSerializer,TicketTransferSerializer
from attendee.models import AffliateEarnings
from events.models import EventMedia,Event
from .models import FavoriteEvent
from public.response import api_response
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from django.contrib.auth.models import User
from transactions.models import TicketTransferHistory
from marketplace.models import MarketListing

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
    


class AddFavoriteEventView(generics.CreateAPIView):
    serializer_class = FavoriteEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        event_id = request.data.get("event_id")
        if not event_id:
            return api_response(
                message="Event ID is required",
                status_code=400,
                data={}
            )

        try:
            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return api_response(
                message="Event not found",
                status_code=404,
                data={}
            )

        favorite, created = FavoriteEvent.objects.get_or_create(
            user=request.user,
            event=event
        )

        if not created:
            return api_response(
                message="Event already in favorites",
                status_code=400,
                data={}
            )

        # Serialize the related event
        serializer = self.get_serializer(event)
        return api_response(
            message="Event added to favorites successfully",
            status_code=200,
            data=serializer.data
        )

class FavoriteEventListView(generics.ListAPIView):
    serializer_class = FavoriteEventSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    ordering_fields = ["created_at", "event__start_datetime"]
    search_fields = ["title"]
    filterset_fields = {
        "event__category": ["exact"],
        "event__start_datetime": ["gte", "lte"],
        "tickets__price": ["gte", "lte"],
    }

    def get_queryset(self):
        # get all event IDs the user has favorited
        favorite_event_ids = FavoriteEvent.objects.filter(user=self.request.user).values_list("event_id", flat=True)
        # fetch those events
        return Event.objects.filter(id__in=favorite_event_ids).distinct()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="User favourite events retrieved successfully",
            status_code=200,
            data=serializer.data
        )

class RemoveFavoriteEventView(generics.DestroyAPIView):
    serializer_class = FavoriteEventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        event_id = self.kwargs.get("event_id")
        try:
            return FavoriteEvent.objects.get(user=self.request.user, event_id=event_id)
        except FavoriteEvent.DoesNotExist:
            return None

    def delete(self, request, *args, **kwargs):
        favorite = self.get_object()
        if not favorite:
            return api_response(
                message="Favorite not found",
                status_code=404,
                data={}
            )

        # Serialize the related event before deleting
        serializer = self.get_serializer(favorite.event)
        favorite.delete()

        return api_response(
            message="Event removed from favorites",
            status_code=200,
            data=serializer.data
        )
    


class TransferTicketView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = TicketTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        ticket_id = serializer.validated_data["ticket_id"]
        recipient_email = serializer.validated_data["recipient_email"]

        with transaction.atomic():

            # Lock the ticket row to prevent race conditions
            ticket = get_object_or_404(
                IssuedTicket.objects.select_for_update(),
                id=ticket_id,
                owner=request.user,
                status="active"
            )

            is_listed = MarketListing.objects.filter(
                ticket=ticket,
                status="active"
            ).exists()

            if is_listed:
                return api_response(
                    message="You cannot transfer a ticket that is listed in the marketplace",
                    status_code=400,
                    data={}
                )


            # Find recipient
            try:
                recipient = User.objects.get(email=recipient_email)
            except User.DoesNotExist:
                return api_response(
                    message="Recipient does not have an account",
                    status_code=404,
                    data={}
                )

            if recipient == request.user:
                return api_response(
                    message="You cannot transfer ticket to yourself",
                    status_code=400,
                    data={}
                )

            # Store previous owner
            previous_owner = ticket.owner

            # Update ticket
            ticket.owner = recipient
            ticket.status = "transferred"
            ticket.transferred_at = timezone.now()

            # Preserve original owner if first transfer
            if not ticket.original_owner:
                ticket.original_owner = previous_owner

            ticket.save()

            # Create transfer history
            TicketTransferHistory.objects.create(
                ticket=ticket,
                from_user=previous_owner,
                to_user=recipient,
                price=ticket.order_ticket.price  # or however you store price
            )

        return api_response(
            message="Ticket transferred successfully",
            status_code=200,
            data={
                "ticket_id": str(ticket.id),
                "new_owner": recipient.email,
                "status": ticket.status
            }
        )