from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Sum, Count,Prefetch
from django.http import Http404
from transactions.models import Order,IssuedTicket
from .filters import TicketDashboardFilter,FavoriteEventFilter
from .serializers import (TicketDashboardSerializer,FavoriteEventSerializer,TicketTransferSerializer,AffiliateEarningHistorySerializer,
                          AffiliateLinkSerializer,WithdrawalHistorySerializer,WithdrawalRequestSerializer,PayoutInformationSerializer,
                          AttendeeProfileSerializer,TwoFactorToggleSerializer,ChangePasswordSerializer,NotificationSettingsSerializer,
                          GroupMemberSerializer,TicketGroupSerializer)
from events.models import EventMedia,Event
from .models import FavoriteEvent,AffliateEarnings,AffiliateLink,Attendee,TwoFactorAuths,TicketGroup,GroupMember,AccountDeletionRequest
from public.response import api_response
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from django.contrib.auth.models import User
from transactions.models import TicketTransferHistory,Withdrawal
from marketplace.models import MarketListing
from public.serializers import EventListSerializer
from django.db.models.functions import ExtractMonth
from django.utils.timezone import now
from django.utils.dateparse import parse_date
import uuid
from attendee.models import PayoutInformation
from decimal import Decimal
from notification.models import NotificationSettings
from drf_spectacular.utils import extend_schema, inline_serializer,OpenApiParameter
from rest_framework import serializers



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

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Dashboard retrieved successfully",
                status_code=200,
                data={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                    "results": serializer.data
                }
            )

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="Dashboard retrieved successfully",
            status_code=200,
            data=serializer.data
        )
    

@extend_schema(
    request=inline_serializer(
        name="AddFavoriteEventRequest",
        fields={
            "event_id": serializers.UUIDField(),  # or serializers.IntegerField() depending on your PK
        }
    ),
    responses={
        200: inline_serializer(
            name="AddFavoriteEventResponse",
            fields={
                "message": serializers.CharField(),
                "status_code": serializers.IntegerField(),
                "data": serializers.DictField()  # the serialized Event
            }
        ),
        400: inline_serializer(
            name="AddFavoriteEventBadRequest",
            fields={
                "message": serializers.CharField(),
                "status_code": serializers.IntegerField(),
                "data": serializers.DictField()
            }
        ),
        404: inline_serializer(
            name="AddFavoriteEventNotFound",
            fields={
                "message": serializers.CharField(),
                "status_code": serializers.IntegerField(),
                "data": serializers.DictField()
            }
        )
    },
    description="Add an event to the authenticated user's favorites."
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
    search_fields = ["title","category"]
    filterset_fields = {
        "category__id": ["exact"],        # model relation
        "start_datetime": ["gte", "lte"],
        "tickets__price": ["gte", "lte"],
    }

    def get_queryset(self):
        # get all event IDs the user has favorited
        favorite_event_ids = FavoriteEvent.objects.filter(user=self.request.user).values_list("event_id", flat=True)
        # fetch those events
        return Event.objects.filter(id__in=favorite_event_ids).distinct()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Favourite retrieved successfully",
                status_code=200,
                data={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                    "results": serializer.data
                }
            )

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="Favouriteretrieved successfully",
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
    


@extend_schema(
    request=TicketTransferSerializer,
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




#AFFLIATE FEATURES 
@extend_schema(
    description="Retrieve affiliate dashboard summary for the current user",
    responses=inline_serializer(
        name="AffiliateDashboardResponse",
        fields={
            "total_earnings": serializers.FloatField(),
            "earnings_this_week": serializers.FloatField(),
            "earnings_this_month": serializers.FloatField(),
            "pending_withdrawals": serializers.FloatField(),
            "available_to_withdraw": serializers.FloatField(),
        }
    )
)
class AffiliateDashboardView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        # All links for this affiliate
        links = AffiliateLink.objects.filter(user=user)

        # All earnings
        all_earnings = AffliateEarnings.objects.filter(link__in=links)

        # Total earnings
        total_earnings = all_earnings.aggregate(total=Sum("earning"))["total"] or 0

        now = timezone.now()
        start_of_week = now - timezone.timedelta(days=now.weekday())  # Monday
        start_of_month = now.replace(day=1)

        # Earnings this week
        earnings_this_week = all_earnings.filter(created_at__gte=start_of_week).aggregate(total=Sum("earning"))["total"] or 0

        # Earnings this month
        earnings_this_month = all_earnings.filter(created_at__gte=start_of_month).aggregate(total=Sum("earning"))["total"] or 0

        # Pending withdrawals & available to withdraw
        # For simplicity, let's assume withdrawals are tracked elsewhere
        pending_withdrawals = 0
        available_to_withdraw = total_earnings - pending_withdrawals

    
        return api_response(
            message="Affliate Data Listed successfully",
            status_code=200,
            data={
                "total_earnings": total_earnings,
                "earnings_this_week": earnings_this_week,
                "earnings_this_month": earnings_this_month,
                "pending_withdrawals": pending_withdrawals,
                "available_to_withdraw": available_to_withdraw
            }
        )
    


class AffiliateEventsView(generics.ListAPIView):
    serializer_class = EventListSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    search_fields = ["title"]

    def get_queryset(self):
        queryset = Event.objects.filter(status="active", affiliate_enabled=True).distinct().order_by('-created_at')

        # Optional filters from query params

        category = self.request.query_params.get("category")
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if category:
            queryset = queryset.filter(category_id=category)  
        if start_date and end_date:
            queryset = queryset.filter(
                start_datetime__date__gte=start_date,
                end_datetime__date__lte=end_date
            )

        return queryset.distinct()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Affiliate Events retrieved successfully",
                status_code=200,
                data={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                    "results": serializer.data
                }
            )

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="Affiliate Events retrieved successfully",
            status_code=200,
            data=serializer.data
        )
    


@extend_schema(
    description="Retrieve affiliate dashboard graph data for the current user",
    # no request body needed for GET, but if you allow query params you can declare them:
    parameters=[
        OpenApiParameter(
            name="year",
            description="Optional year to filter earnings",
            required=False,
            type=int,
        ),
        OpenApiParameter(
            name="month",
            description="Optional month to filter earnings",
            required=False,
            type=int,
        ),
    ],
    responses=inline_serializer(
        name="AffiliateGraphResponse",
        fields={
            "monthly_earnings": serializers.ListField(
                child=serializers.DictField(
                    child=serializers.FloatField()
                )
            ),
            "total_clicks": serializers.IntegerField(),
            "total_clicks_change_pct": serializers.FloatField(),
            "total_sales": serializers.IntegerField(),
            "total_sales_change_pct": serializers.FloatField(),
            "conversion_rate": serializers.FloatField(),
            "conversion_rate_change_pct": serializers.FloatField(),
            "total_earnings": serializers.FloatField(),
            "total_earnings_change_pct": serializers.FloatField(),
        }
    )
)
class AffiliateGraphView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        today = now()
        current_year = today.year
        current_month = today.month

        
        monthly_data = (
            AffliateEarnings.objects
            .filter(link__user=user, created_at__year=current_year)
            .annotate(month=ExtractMonth("created_at"))
            .values("month")
            .annotate(total_earning=Sum("earning"))
            .order_by("month")
        )

        # Fill all months and calculate % change vs previous month
        earnings_list = []
        prev = None
        for m in range(1, 13):
            month_earning = next((x["total_earning"] for x in monthly_data if x["month"] == m), 0)
            change_pct = ((month_earning - prev) / prev * 100) if prev and prev > 0 else 0
            earnings_list.append({
                "month": m,
                "earning": month_earning,
                "change_pct": round(change_pct, 2)
            })
            prev = month_earning

        # Determine previous month/year
        if current_month == 1:
            prev_month = 12
            prev_year = current_year - 1
        else:
            prev_month = current_month - 1
            prev_year = current_year

        # Current month aggregates
        current_clicks = AffiliateLink.objects.filter(
            user=user, created_at__year=current_year, created_at__month=current_month
        ).aggregate(total=Sum("clicks"))["total"] or 0

        current_sales = AffiliateLink.objects.filter(
            user=user, created_at__year=current_year, created_at__month=current_month
        ).aggregate(total=Sum("sales"))["total"] or 0

        current_earnings = AffliateEarnings.objects.filter(
            link__user=user, created_at__year=current_year, created_at__month=current_month
        ).aggregate(total=Sum("earning"))["total"] or 0

        current_conversion_rate = (current_sales / current_clicks * 100) if current_clicks > 0 else 0

        # Previous month aggregates
        prev_clicks = AffiliateLink.objects.filter(
            user=user, created_at__year=prev_year, created_at__month=prev_month
        ).aggregate(total=Sum("clicks"))["total"] or 0

        prev_sales = AffiliateLink.objects.filter(
            user=user, created_at__year=prev_year, created_at__month=prev_month
        ).aggregate(total=Sum("sales"))["total"] or 0

        prev_earnings = AffliateEarnings.objects.filter(
            link__user=user, created_at__year=prev_year, created_at__month=prev_month
        ).aggregate(total=Sum("earning"))["total"] or 0

        prev_conversion_rate = (prev_sales / prev_clicks * 100) if prev_clicks > 0 else 0

        # Helper to calculate % change
        def pct_change(current, previous):
            if previous > 0:
                return round((current - previous) / previous * 100, 2)
            return 0


        # Prepare dashboard data
        dashboard_data = {
            "monthly_earnings": earnings_list,
            "total_clicks": current_clicks,
            "total_clicks_change_pct": pct_change(current_clicks, prev_clicks),
            "total_sales": current_sales,
            "total_sales_change_pct": pct_change(current_sales, prev_sales),
            "conversion_rate": round(current_conversion_rate, 2),
            "conversion_rate_change_pct": pct_change(current_conversion_rate, prev_conversion_rate),
            "total_earnings": current_earnings,
            "total_earnings_change_pct": pct_change(current_earnings, prev_earnings),
        }

        return api_response(
            message="Affiliate dashboard retrieved successfully",
            status_code=200,
            data=dashboard_data
        )
    


class AffiliateEarningHistoryView(generics.ListAPIView):
    serializer_class = AffiliateEarningHistorySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["link__event__title", "link__event__category__name"] 
    ordering_fields = ["created_at", "earning"]

    def get_queryset(self):
        user = self.request.user
        queryset = AffliateEarnings.objects.filter(link__user=user)

        # Optional date range filter: ?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if start_date:
            queryset = queryset.filter(created_at__date__gte=parse_date(start_date))
        if end_date:
            queryset = queryset.filter(created_at__date__lte=parse_date(end_date))

        return queryset.order_by("-created_at")  # newest first

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Affiliate earning history retrieved successfully",
                status_code=200,
                data={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                    "results": serializer.data
                }
            )

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="Affiliate earning history retrieved successfully",
            status_code=200,
            data=serializer.data
        )


@extend_schema(
    request=inline_serializer(
        name="GenerateAffiliateLinkRequest",
        fields={
            "event_id": serializers.UUIDField(),
        }
    ),
    responses=AffiliateLinkSerializer,  # keep your response serializer
    description="Generate an affiliate link for an event"
)
class GenerateAffiliateLinkView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = AffiliateLinkSerializer 
    
    def post(self, request):
        user = request.user
        event_id = request.data.get("event_id")

        if not event_id:
            return  api_response(
            message="event_id is required",
            status_code=400,
            data={}
        )

        try:
            event = Event.objects.get(id=event_id, affiliate_enabled=True)
        except Event.DoesNotExist:
            return api_response(
            message="Event not found or affiliate not enabled",
            status_code=404,
            data={}
        )

        if event.host.user == user:
            return api_response(
                message="You cannot generate an affiliate link for your own event",
                status_code=403,
                data={}
            )

        # Check if user already has a link for this event
        link, created = AffiliateLink.objects.get_or_create(
            user=user,
            event=event,
            defaults={"code": uuid.uuid4()}  
        )

        serializer = AffiliateLinkSerializer(link, context={"request": request})
        return  api_response(
            message="Link Generated",
            status_code=200,
            data=serializer.data
        )
  

@extend_schema(
    request=WithdrawalRequestSerializer,
)
class RequestWithdrawalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = WithdrawalRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        amount = serializer.validated_data["amount"]
        payout_account_id = serializer.validated_data["payout_account_id"]

        if amount <= Decimal("0.00"):
            return api_response(
                message="Withdrawal amount must be greater than zero",
                status_code=400,
                data={}
            )

        # ✅ Idempotency Key (Required)
        idempotency_key = request.headers.get("Idempotency-Key")

        if not idempotency_key:
            return api_response(
                message="Idempotency-Key header is required",
                status_code=400,
                data={}
            )

        # Check if request was already processed
        existing_withdrawal = Withdrawal.objects.filter(
            idempotency_key=idempotency_key,
            user=request.user
        ).first()

        if existing_withdrawal:
            return api_response(
                message="Withdrawal already submitted",
                status_code=200,
                data={"withdrawal_id": existing_withdrawal.id}
            )

        try:
            payout_account = PayoutInformation.objects.get(
                id=payout_account_id,
                user=request.user
            )
        except PayoutInformation.DoesNotExist:
            return api_response(
                message="Invalid payout account",
                status_code=400,
                data={}
            )

        with transaction.atomic():

            # 🔒 Lock earnings rows for safety
            total_earnings = (
                AffliateEarnings.objects
                .select_for_update()
                .filter(link__user=request.user, status="succeeded")
                .aggregate(total=Sum("earning"))["total"]
                or Decimal("0.00")
            )

            total_withdrawn = (
                Withdrawal.objects
                .select_for_update()
                .filter(user=request.user)
                .exclude(status="rejected")
                .aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )

            available_balance = total_earnings - total_withdrawn

            if amount > available_balance:
                return api_response(
                    message="Insufficient balance",
                    status_code=400,
                    data={
                        "available_balance": str(available_balance)
                    }
                )

            withdrawal = Withdrawal.objects.create(
                user=request.user,
                payout_account=payout_account,
                amount=amount,
                idempotency_key=uuid.UUID(idempotency_key)
            )

        return api_response(
            message="Withdrawal request submitted successfully",
            status_code=201,
            data={
                "withdrawal_id": withdrawal.id,
                "available_balance": str(available_balance - amount)
            }
        )
    

class WithdrawalHistoryView(generics.ListAPIView):
    serializer_class = WithdrawalHistorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Withdrawal.objects
            .filter(user=self.request.user)
            .select_related("payout_account")
            .order_by("-created_at")
        )
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Affiliate earning history retrieved successfully",
                status_code=200,
                data={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                    "results": serializer.data
                }
            )

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="Withdrawal history Retrieved",
            status_code=200,
            data=serializer.data
        )
    

class PayoutInformationListView(generics.ListAPIView):
    serializer_class = PayoutInformationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return PayoutInformation.objects.filter(user=self.request.user)
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Affiliate earning history retrieved successfully",
                status_code=200,
                data={
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
                    "results": serializer.data
                }
            )

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="Payment Methods Retrieved",
            status_code=200,
            data=serializer.data
        )
    

# views.py

class AttendeeProfileView(generics.ListAPIView):
    serializer_class = AttendeeProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Attendee.objects.filter(user=self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset().first()

        if not queryset:
            return api_response(
                message="Profile not found",
                status_code=404,
                data={}
            )

        serializer = self.get_serializer(queryset)

        return api_response(
            message="Profile retrieved successfully",
            status_code=200,
            data=serializer.data
        )
    


class UpdateAttendeeProfileView(generics.UpdateAPIView):
    serializer_class = AttendeeProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        try:
            return Attendee.objects.get(user=self.request.user)
        except Attendee.DoesNotExist:
            raise Http404("Profile not found")

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", True)  # allow PATCH
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return api_response(
            message="Profile updated successfully",
            status_code=200,
            data=serializer.data
        )
    

@extend_schema(
    request=TwoFactorToggleSerializer,
)
class ToggleTwoFactorView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        two_factor, created = TwoFactorAuths.objects.get_or_create(
            user=request.user
        )

        serializer = TwoFactorToggleSerializer(
            two_factor,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return api_response(
            message="Two-factor settings updated successfully",
            status_code=200,
            data=serializer.data
        )
    


@extend_schema(
    request=ChangePasswordSerializer,
)
class ChangePasswordView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user

        if not user.check_password(serializer.validated_data["old_password"]):
            return api_response(
                message="Old password is incorrect",
                status_code=400,
                data={}
            )

        user.set_password(serializer.validated_data["new_password"])
        user.save()

        return api_response(
            message="Password changed successfully",
            status_code=200,
            data={}
        )
    


class NotificationSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = NotificationSettingsSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        settings_obj, created = NotificationSettings.objects.get_or_create(
            user=self.request.user
        )
        return settings_obj

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        return api_response(
            message="Notification settings retrieved successfully",
            status_code=200,
            data=serializer.data
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", True)  # allow PATCH
        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return api_response(
            message="Notification settings updated successfully",
            status_code=200,
            data=serializer.data
        )
    

@extend_schema(
    request=inline_serializer(
        name="CreateGroupRequest",
        fields={
            "name": serializers.CharField(),
            "members": serializers.ListField(
                child=serializers.DictField(
                    child=serializers.CharField()
                ),
                required=False,
                help_text="List of members with their emails"
            ),
        },
    ),
    responses=TicketGroupSerializer,
)
class CreateGroupView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        name = request.data.get("name")
        members_data = request.data.get("members", [])

        if not name:
            return api_response(
                message="Group name is required",
                status_code=400,
                data={}
            )

        if not isinstance(members_data, list):
            return api_response(
                message="Members must be a list",
                status_code=400,
                data={}
            )

        emails = []
        for member in members_data:
            email = member.get("email")
            if not email:
                return api_response(
                    message="Each member must have an email",
                    status_code=400,
                    data={}
                )
            emails.append(email.lower())

        # Remove duplicates
        emails = list(set(emails))

        # Prevent adding yourself again
        if request.user.email.lower() in emails:
            return api_response(
                message="You are automatically added as group owner",
                status_code=400,
                data={}
            )

        # Check if all users exist BEFORE creating group
        existing_users = User.objects.filter(email__in=emails)
        existing_emails = set(existing_users.values_list("email", flat=True))

        missing_emails = set(emails) - existing_emails

        if missing_emails:
            return api_response(
                message="Some users do not have an account",
                status_code=400,
                data={
                    "non_existing_users": list(missing_emails)
                }
            )

        with transaction.atomic():
            group = TicketGroup.objects.create(
                name=name,
                owner=request.user
            )

            # Add owner automatically
            GroupMember.objects.create(
                group=group,
                user=request.user,
            )

            # Add other members
            for user in existing_users:
                GroupMember.objects.create(
                    group=group,
                    user=user,
                )

        serializer = TicketGroupSerializer(group)

        return api_response(
            message="Group created successfully",
            status_code=201,
            data=serializer.data
        )

class MyGroupsView(generics.ListAPIView):
    serializer_class = TicketGroupSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            TicketGroup.objects
            .filter(members=self.request.user)
            .prefetch_related("group_members__user")
            .distinct()
            .order_by("-created_at")
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="Groups retrieved successfully",
            status_code=200,
            data=serializer.data
        )
    

@extend_schema(
    request=TicketGroupSerializer,
)
class UpdateGroupView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request, group_id):
        group = get_object_or_404(TicketGroup, id=group_id)

        if group.owner != request.user:
            return api_response("Not allowed", 403, {})

        updated = False

        # Update group name
        name = request.data.get("name")
        if name:
            group.name = name
            group.save()
            updated = True

        # Add new members (optional)
        members_data = request.data.get("members", [])
        if members_data:
            emails = [m.get("email").lower() for m in members_data if m.get("email")]
            existing_users = User.objects.filter(email__in=emails)
            existing_emails = set(existing_users.values_list("email", flat=True))
            missing = set(emails) - existing_emails
            if missing:
                return api_response(
                    "Some users do not exist",
                    400,
                    {"non_existing_users": list(missing)}
                )

            # Add only users not already members
            for user in existing_users:
                if not GroupMember.objects.filter(group=group, user=user).exists():
                    GroupMember.objects.create(group=group, user=user)
                    updated = True

        serializer = TicketGroupSerializer(group)

        if updated:
            return api_response("Group updated", 200, serializer.data)
        else:
            return api_response("No changes applied", 200, serializer.data)


@extend_schema(
    request=None,  # DELETE has no body
    responses={
        200: inline_serializer(
            name="DeleteGroupResponse",
            fields={}  # empty response data
        ),
        403: None,
        404: None,
    },
    description="Delete a group. Only the group owner can perform this action."
)
class DeleteGroupView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, group_id):
        group = get_object_or_404(TicketGroup, id=group_id)

        if group.owner != request.user:
            return api_response("Not allowed", 403, {})

        group.delete()

        return api_response("Group deleted successfully", 200, {})
    


@extend_schema(
    request=inline_serializer(
        name="RemoveGroupMemberRequest",
        fields={
            "email": serializers.EmailField(),
        },
    ),
    responses={
        200: inline_serializer(
            name="RemoveGroupMemberResponse",
            fields={}  # empty dict since you return empty data
        ),
        400: None,
        403: None,
        404: None,
    },
    description="Remove a member from a group. Only the group owner can perform this action."
)
class RemoveGroupMemberView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, group_id):
        email = request.data.get("email")

        if not email:
            return api_response(
                message="Member email is required",
                status_code=400,
                data={}
            )

        group = get_object_or_404(TicketGroup, id=group_id)

        # Only owner can remove
        if group.owner != request.user:
            return api_response(
                message="Only the group owner can remove members",
                status_code=403,
                data={}
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return api_response(
                message="User does not have an account",
                status_code=404,
                data={}
            )

        # Prevent owner removal
        if user == group.owner:
            return api_response(
                message="Owner cannot be removed from the group",
                status_code=400,
                data={}
            )

        member = GroupMember.objects.filter(group=group, user=user).first()

        if not member:
            return api_response(
                message="User is not a member of this group",
                status_code=404,
                data={}
            )

        member.delete()

        return api_response(
            message="Member removed successfully",
            status_code=200,
            data={}
        )
    


    
@extend_schema(
    request=inline_serializer(
        name="ActivitySharingRequest",
        fields={
            "show_events": serializers.BooleanField(required=False),
            "show_favorites": serializers.BooleanField(required=False),
        },
    ),
    responses=inline_serializer(
        name="ActivitySharingResponse",
        fields={
            "show_events_attending": serializers.BooleanField(),
            "show_favorites": serializers.BooleanField(),
        },
    ),
    description="Update which activity types (events, favorites) are visible on your profile."
)
class ActivitySharingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        show_events = request.data.get("show_events")
        show_favorites = request.data.get("show_favorites")

        profile = request.user.attendee_profile

        if show_events is not None:
            profile.show_events_attending = bool(show_events)
        if show_favorites is not None:
            profile.show_favorites = bool(show_favorites)

        profile.save()
        return api_response(
            "Activity sharing updated",
            200,
            {
                "show_events_attending": profile.show_events_attending,
                "show_favorites": profile.show_favorites
            }
        )
    

class DownloadMyDataView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user

        # Collect data (simplified, you can serialize all related models)
        data = {
            "user": {
                "email": user.email,
                "username": user.username,
            },
            "profile": {
                "full_name": user.attendee_profile.full_name,
                "phone_number": user.attendee_profile.phone_number,
                "dob": user.attendee_profile.dob,
                "gender": user.attendee_profile.gender,
                "country": user.attendee_profile.country,
                "state": user.attendee_profile.state,
                "city": user.attendee_profile.city,
            },
            # Add favorites, orders, tickets, groups, etc.
        }

        # Here you can attach this data to email or generate a file
        # send_mail(
        #     subject="Your Data Download",
        #     message=str(data),  # ideally JSON attachment
        #     from_email="no-reply@yourdomain.com",
        #     recipient_list=[user.email]
        # )

        return api_response("Your data has been sent to your email", 200, {})
    


@extend_schema(
    request=inline_serializer(
        name="RequestAccountDeletionRequest",
        fields={
            "password": serializers.CharField(write_only=True),
        },
    ),
    responses={
        201: inline_serializer(
            name="RequestAccountDeletionResponse",
            fields={
                "request_id": serializers.UUIDField(),
            },
        ),
        400: None,
    },
    description="Submit an account deletion request. Requires password confirmation.",
)
class RequestAccountDeletionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        password = request.data.get("password")

        user = request.user
        if not user.check_password(password):
            return api_response("Incorrect password", 400, {})

        deletion_request = AccountDeletionRequest.objects.create(
            user=user,
        )

        return api_response(
            "Account deletion request submitted. Admin will review it.",
            201,
            {"request_id": str(deletion_request.id)}
        )
    

@extend_schema(
    request=PayoutInformationSerializer,
)
class ListPayoutAccountsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        accounts = PayoutInformation.objects.filter(user=request.user)
        serializer = PayoutInformationSerializer(accounts, many=True)
        return api_response(
            message="Payout accounts retrieved successfully",
            status_code=200,
            data=serializer.data
        )


@extend_schema(
    request=PayoutInformationSerializer,
)
class AddPayoutAccountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = PayoutInformationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # If user sets this as default, unset any existing defaults
        if serializer.validated_data.get("is_default", False):
            PayoutInformation.objects.filter(user=request.user).update(is_default=False)

        account = serializer.save(user=request.user)

        return api_response(
            message="Payout account added successfully",
            status_code=201,
            data=PayoutInformationSerializer(account).data
        )