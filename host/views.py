from decimal import Decimal
import uuid
from rest_framework import serializers
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from attendee.models import AccountDeletionRequest, Attendee
from events.models import Event
from host.models import Host, HostSubscription
from host.services.RenewSubscriptionService import RenewSubscriptionService, SubscriptionError
from host.services.brevoservice import CampaignError, CampaignService   
from host.helpers import _apply_date_range, _available_balance, _base_orders, _get_host, _host_orders, _host_payouts, _host_revenue, _next_friday, _pct_change, _period_delta
from host.services.service import AffiliateService, CheckInService, DashboardService, DownloadEventAttendeeService, PromoCodeError, PromoCodeService, SalesCardService, SalesGraphService, TransactionService
from payments.models import PayoutInformation
from transactions.models import Order, OrderTicket, Withdrawal
from .serializers import AffiliateCardSerializer, AffiliateListSerializer, AttendeeProfileSerializer, ChangePasswordSerializer, CheckInAttendeeSerializer, CheckInCardSerializer, CustomerDetailCardSerializer, CustomerListSerializer, CustomerListSerializer, CustomerOrderHistorySerializer, DashboardCardSerializer, EmailCampaignCreateSerializer, EmailCampaignListSerializer, EventSerializer,EventCardSerializer,EventTableSerializer, GeoBreakdownSerializer, HostActivitySerializer, HostNotificationSerializer, HostSubscriptionStatusSerializer, HostWithdrawalRequestSerializer, PayoutInformationSerializer, PromoCodeCreateSerializer, PromoCodeListSerializer, RevenueCardSerializer, RevenueChartPointSerializer, RevenuePointSerializer, SalesBreakdownSerializer, SalesCardSerializer, ScanInputSerializer, ScanResultSerializer, SingleEmailCampaignSerializer, TransactionHistorySerializer, TrendingTicketSerializer, WeekAnalysisSerializer, WithdrawalHistorySerializer,DownloadEventAttendeeSerializer,PrivacySettingsSerializer
from public.response import flatten_errors,api_response
from django.http import Http404
from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.http import Http404
from .utils import EventDashboardFilter, apply_date_range_qs,pagination_data
from django.http import Http404
from django.db.models import (
    Count, Sum, Max, Min, Q, OuterRef, Subquery, DecimalField
)
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
from django.utils import timezone
from .permissions import IsEventOwner
from rest_framework import generics, permissions, filters
from rest_framework.response import Response
from django.db import transaction
from public.response import api_response
from .serializers import (
    CustomerListSerializer,
    AttendeeProfileSerializer,
    CustomerDetailCardSerializer,
    RevenueChartPointSerializer,
    CustomerOrderHistorySerializer,
)
from datetime import date, timedelta

from drf_spectacular.utils import OpenApiResponse, extend_schema, OpenApiParameter, inline_serializer
from drf_spectacular.types import OpenApiTypes
from .mixin import PlanFeatureMixin


class EventCreateView(PlanFeatureMixin,generics.CreateAPIView):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticated]

    check_active_events    = True
    check_ticket_types     = True
    check_promo_codes      = True
    check_team_permissions = True
    check_affiliate = True
    check_ticket_limit     = True

    def get_serializer_context(self):
        # pass request to serializer so it can access user
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context
   
    def create(self, request, *args, **kwargs):
        if getattr(self, "_blocked_response", None):
            return self._blocked_response
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=False)  
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)
        self.perform_create(serializer)
        return api_response(
            message="Event created successfully",
            status_code=201,
            data=serializer.data
        )
    

class EventUpdateView(generics.UpdateAPIView):
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticated,IsEventOwner]
    lookup_field = "id"   

    def get_queryset(self):
        # Only allow host to update their own events
        user = self.request.user

        if not hasattr(user, "host_profile"):
            return Event.objects.none()

        return Event.objects.filter(host=user.host_profile)

    def update(self, request, *args, **kwargs):
        partial = True  # This allows updating only provided fields
        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial
        )

        if not serializer.is_valid():
            return api_response(
                message=serializer.errors,
                status_code=400
            )

        self.perform_update(serializer)

        return api_response(
            message="Event updated successfully",
            status_code=200,
            data=serializer.data
        )


class EventDashboardView(generics.ListAPIView):
    serializer_class = EventTableSerializer
    permission_classes = [permissions.IsAuthenticated]

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    filterset_class = EventDashboardFilter
    search_fields = ["title"]
    ordering_fields = ["title", "start_datetime", "created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        user = self.request.user

        if not hasattr(user, "host_profile"):
            raise Http404("You are not a host or have no events.")

        return Event.objects.filter(host=user.host_profile).select_related("category", "event_location").prefetch_related("tickets", "media").annotate(
                total_revenue=Sum(
                    "order__total_amount",
                    filter=Q(order__status="completed",order__marketplace_listing__isnull=True),
                )
            )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        # ---- Card Counts ----
        base_queryset = Event.objects.filter(host=request.user.host_profile)

        card_data = {
            "live": base_queryset.filter(status="active").count(),
            "draft": base_queryset.filter(status="draft").count(),
            "ended": base_queryset.filter(status="ended").count(),
            "sold_out": base_queryset.filter(status="sold-out").count(),
        }

        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)

            return api_response(
                message="Events retrieved successfully",
                status_code=200,
                data={
                    **pagination_data(self.paginator),
                    "cards": card_data,
                    "results": serializer.data,
                }
            )

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="Events retrieved successfully",
            status_code=200,
            data={
                "cards": card_data,
                "results": serializer.data
            }
        )





### CDUSTOMER ANALYTICS DASHBOARD ###

@extend_schema(
    operation_id="customer_list",
    parameters=[
        OpenApiParameter("date_range", OpenApiTypes.STR, description="day | week | month"),
        OpenApiParameter("event", OpenApiTypes.UUID, description="Filter by event UUID"),
        OpenApiParameter("ticket_type", OpenApiTypes.INT, description="Filter by Ticket PK"),
        OpenApiParameter("search", OpenApiTypes.STR, description="Search name or email"),
    ],
    responses=CustomerListSerializer(many=True),
)
class CustomerListView(PlanFeatureMixin,generics.ListAPIView):
    """
    GET /customers/

    Query params
    ------------
    date_range  : day | week | month   — rolls the window for both cards AND table
    event       : <event UUID>         — scope everything to one event
    ticket_type : <ticket int PK>      — scope to a specific ticket type
    search      : name or email        — searches within results
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CustomerListSerializer  # satisfies drf-spectacular introspection
    required_feature = "customer_profile_insights"

    def _get_host(self):
        return getattr(self.request.user, "host_profile", None)

    def _cards(self, host, event_id, date_range, ticket_type):
        """Cards reflect the SAME filters as the table so numbers always match."""
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        base = _base_orders(host, event_id=event_id, date_range=date_range)
        if ticket_type:
            base = base.filter(tickets__ticket_id=ticket_type)

        all_customers = base.values("user").distinct().count()

        # new this month: first-ever order (all-time, same event scope) in this calendar month
        first_order_per_user = (
            _base_orders(host, event_id=event_id)
            .values("user")
            .annotate(first_order=Min("created_at"))
        )
        new_this_month = sum(
            1 for r in first_order_per_user
            if r["first_order"] and r["first_order"] >= month_start
        )

        repeat_buyers = (
            base.values("user").annotate(cnt=Count("id")).filter(cnt__gt=1).count()
        )

        per_user = base.values("user").annotate(spent=Sum("total_amount"))
        if per_user.exists():
            total = sum(r["spent"] or 0 for r in per_user)
            avg = round(Decimal(str(total)) / per_user.count(), 2)
        else:
            avg = Decimal("0.00")

        return {
            "total_customers": all_customers,
            "new_this_month":  new_this_month,
            "repeat_buyers":   repeat_buyers,
            "average_spend":   avg,
        }

    def _customer_rows(self, host, event_id, date_range, ticket_type, search):
        base = _base_orders(host, event_id=event_id, date_range=date_range)
        if ticket_type:
            base = base.filter(tickets__ticket_id=ticket_type)

        qs = (
            base
            .values("user__id", "user__email", "user__attendee_profile__full_name")
            .annotate(
                events_attended=Count("id", distinct=True),
                total_spent=Sum("total_amount"),
                last_purchase_date=Max("created_at"),
            )
            .order_by("-total_spent")
        )

        if search:
            qs = qs.filter(
                Q(user__email__icontains=search) |
                Q(user__attendee_profile__full_name__icontains=search)
            )
        return qs

    def list(self, request, *args, **kwargs):
        host = self._get_host()
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        date_range  = request.query_params.get("date_range")       # day|week|month
        event_id    = request.query_params.get("event")            # event UUID
        ticket_type = request.query_params.get("ticket_type")      # ticket int PK
        search      = request.query_params.get("search", "").strip()

        rows  = self._customer_rows(host, event_id, date_range, ticket_type, search)
        cards = self._cards(host, event_id, date_range, ticket_type)

        row_list = list(rows)
        spends    = sorted([float(r.get("total_spent") or 0) for r in row_list], reverse=True)
        threshold = spends[max(0, len(spends) // 10 - 1)] if spends else 0

        page  = self.paginate_queryset(row_list)
        items = page if page is not None else row_list

        serializer = CustomerListSerializer(
            items, many=True, context={"top_threshold": threshold}
        )

        data = {"cards": cards, "results": serializer.data}
        if page is not None:
            # New — 1 line, returns page numbers + extra info
            data.update(pagination_data(self.paginator))

        return api_response(
            message="Customers retrieved successfully", status_code=200, data=data
        )


# ── Customer Detail ────────────────────────────────────────────────────────────

@extend_schema(
    operation_id="customer_detail",
    parameters=[
        OpenApiParameter("date_range", OpenApiTypes.STR, description="day | week | month — KPI window"),
        OpenApiParameter("event", OpenApiTypes.UUID, description="Scope KPI cards + chart to one event"),
        OpenApiParameter("chart_range", OpenApiTypes.STR, description="day | week | month — chart grouping"),
        OpenApiParameter("ticket_type", OpenApiTypes.INT, description="Filter order history by ticket"),
        OpenApiParameter("history_date_range", OpenApiTypes.STR, description="day | week | month — order history window"),
        OpenApiParameter("history_event", OpenApiTypes.UUID, description="Filter order history to one event"),
        OpenApiParameter("search", OpenApiTypes.STR, description="Search order history by event title"),
    ],
    responses=CustomerOrderHistorySerializer(many=True),
)
class CustomerDetailView(PlanFeatureMixin,generics.ListAPIView):
    """
    GET /customers/<user_id>/

    Query params
    ------------
    date_range         : day | week | month  — KPI cards comparison window
    event              : <event UUID>        — scope KPI cards + chart + profile dates
    chart_range        : day | week | month  — revenue chart grouping (independent)
    ticket_type        : <ticket int PK>     — filter order history
    history_date_range : day | week | month  — filter order history date window
    history_event      : <event UUID>        — filter order history to one event
    search             : event title keyword — search order history
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CustomerOrderHistorySerializer  # satisfies drf-spectacular introspection
    required_feature = "customer_profile_insights"

    def _get_host(self):
        return getattr(self.request.user, "host_profile", None)

    def _kpi_with_change(self, host, customer_id, date_range, event_id):
        now          = timezone.now()
        delta        = _period_delta(date_range)
        period_start = now - delta
        prev_start   = period_start - delta

        def _window(start, end, status="completed"):
            qs = Order.objects.filter(
                event__host=host, user_id=customer_id,
                status=status, created_at__gte=start, created_at__lt=end,
            )
            if event_id:
                qs = qs.filter(event_id=event_id)
            return qs

        curr         = _window(period_start, now)
        curr_spent   = curr.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        curr_tickets = (
            OrderTicket.objects.filter(order__in=curr).aggregate(q=Sum("quantity"))["q"] or 0
        )
        curr_refunds = _window(period_start, now, status="refunded").count()

        all_completed = Order.objects.filter(
            event__host=host, user_id=customer_id, status="completed"
        )
        if event_id:
            all_completed = all_completed.filter(event_id=event_id)
        last_order = (
            all_completed.order_by("-created_at").values_list("total_amount", flat=True).first()
        )

        prev         = _window(prev_start, period_start)
        prev_spent   = prev.aggregate(s=Sum("total_amount"))["s"] or Decimal("0")
        prev_tickets = (
            OrderTicket.objects.filter(order__in=prev).aggregate(q=Sum("quantity"))["q"] or 0
        )
        prev_refunds    = _window(prev_start, period_start, status="refunded").count()
        prev_last_order = (
            all_completed.filter(created_at__lt=period_start)
            .order_by("-created_at").values_list("total_amount", flat=True).first()
        )

        return {
            "total_spent":             curr_spent,
            "total_spent_change":      _pct_change(curr_spent, prev_spent),
            "tickets_bought":          curr_tickets,
            "tickets_bought_change":   _pct_change(curr_tickets, prev_tickets),
            "refund_count":            curr_refunds,
            "refund_count_change":     _pct_change(curr_refunds, prev_refunds),
            "last_order_value":        last_order,
            "last_order_value_change": _pct_change(last_order or 0, prev_last_order or 0),
        }

    def _profile(self, host, customer_id, date_range, event_id):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            user = User.objects.select_related("attendee_profile").get(id=customer_id)
        except User.DoesNotExist:
            return None

        attendee = getattr(user, "attendee_profile", None)

        # first/last purchase scoped to same filters as cards
        dates = (
            _base_orders(host, event_id=event_id, date_range=date_range)
            .filter(user_id=customer_id)
            .aggregate(first_purchase=Min("created_at"), last_purchase=Max("created_at"))
        )

        return {
            "user_id":             user.id,
            "full_name":           attendee.full_name         if attendee else "",
            "email":               user.email,
            "phone_number":        attendee.phone_number      if attendee else "",
            "country":             attendee.country           if attendee else "",
            "state":               attendee.state             if attendee else "",
            "city":                attendee.city              if attendee else "",
            "gender":              attendee.gender            if attendee else "",
            "dob":                 attendee.dob               if attendee else None,
            "profile_picture":     attendee.profile_picture   if attendee else None,
            "registration_date":   attendee.registration_date if attendee else None,
            "first_purchase_date": dates["first_purchase"],
            "last_purchase_date":  dates["last_purchase"],
        }

    def _revenue_chart(self, host, customer_id, chart_range, event_id):
        trunc_fn = {"day": TruncDay, "week": TruncWeek, "month": TruncMonth}.get(
            chart_range, TruncMonth
        )
        fmt = {"day": "%Y-%m-%d", "week": "Week of %Y-%m-%d", "month": "%b %Y"}.get(
            chart_range, "%b %Y"
        )

        qs = Order.objects.filter(
            event__host=host, user_id=customer_id, status="completed"
        )
        if event_id:
            qs = qs.filter(event_id=event_id)

        qs = (
            qs.annotate(period=trunc_fn("created_at"))
            .values("period")
            .annotate(amount=Sum("total_amount"))
            .order_by("period")
        )

        return [
            {"label": row["period"].strftime(fmt), "amount": row["amount"]}
            for row in qs if row["period"]
        ]

    def _order_history(self, host, customer_id, ticket_type, date_range, event_id, search):
        qs = (
            Order.objects
            .select_related("event", "event__category")
            .prefetch_related("event__media", "tickets")
            .filter(event__host=host, user_id=customer_id)
        )

        if event_id:
            qs = qs.filter(event_id=event_id)
        if ticket_type:
            qs = qs.filter(tickets__ticket_id=ticket_type)
        if date_range:
            qs = _apply_date_range(qs, date_range)
        if search:
            qs = qs.filter(event__title__icontains=search)

        results = []
        for order in qs.order_by("-created_at"):
            event       = order.event
            total_qty   = sum(t.quantity for t in order.tickets.all())
            featured    = event.media.filter(is_featured=True).first()
            any_media   = event.media.first()
            event_image = (
                featured.image_url if featured
                else (any_media.image_url if any_media else None)
            )
            results.append({
                "order_id":       order.id,
                "event_id":       event.id,
                "event_name":     event.title,
                "event_image":    event_image,
                "event_category": event.category.name if event.category else None,
                "purchase_date":  order.created_at,
                "quantity":       total_qty,
                "amount":         order.total_amount,
                "status":         order.status,
            })
        return results

    def list(self, request, *args, **kwargs):
        host = self._get_host()
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        customer_id = kwargs.get("user_id")

        # top-section filters
        date_range  = request.query_params.get("date_range", "month")
        event_id    = request.query_params.get("event")

        # chart filter (independent grouping)
        chart_range = request.query_params.get("chart_range", "month")

        # order history filters
        ticket_type        = request.query_params.get("ticket_type")
        history_date_range = request.query_params.get("history_date_range")
        history_event_id   = request.query_params.get("history_event")
        search             = request.query_params.get("search", "").strip()

        profile = self._profile(host, customer_id, date_range, event_id)
        if profile is None:
            return api_response(message="Customer not found.", status_code=404)

        cards      = self._kpi_with_change(host, customer_id, date_range, event_id)
        chart_data = self._revenue_chart(host, customer_id, chart_range, event_id)

        history_rows = self._order_history(
            host, customer_id,
            ticket_type=ticket_type,
            date_range=history_date_range,
            event_id=history_event_id,
            search=search,
        )

        page = self.paginate_queryset(history_rows)
        history_serializer = CustomerOrderHistorySerializer(
            page if page is not None else history_rows, many=True
        )

        paginated_history = {"results": history_serializer.data}
        if page is not None:
            paginated_history["count"]    = self.paginator.page.paginator.count
            paginated_history["next"]     = self.paginator.get_next_link()
            paginated_history["previous"] = self.paginator.get_previous_link()

        return api_response(
            message="Customer detail retrieved successfully",
            status_code=200,
            data={
                "cards":         CustomerDetailCardSerializer(cards).data,
                "profile":       AttendeeProfileSerializer(profile).data,
                "revenue_chart": RevenueChartPointSerializer(chart_data, many=True).data,
                "order_history": paginated_history,
            },
        )



# PAYMENT SECTION
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
                    **pagination_data(self.paginator),
                    "results": serializer.data
                }
            )

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="Withdrawal history Retrieved",
            status_code=200,
            data=serializer.data
        )
    


@extend_schema(
    operation_id="host_revenue_overview",
    parameters=[
        OpenApiParameter(
            "date_range", OpenApiTypes.STR,
            description="day | week | month — filters revenue and payout totals"
        ),
    ],
    responses=RevenueCardSerializer,
)
class HostRevenueOverviewView(generics.ListAPIView):
    """
    GET /finance/overview/

    Also returns a paginated list of the host's withdrawal history,
    which respects the same date_range filter.

    Query params
    ────────────
    date_range : day | week | month
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = WithdrawalHistorySerializer   # for drf-spectacular

    def _get_host(self):
        return getattr(self.request.user, "host_profile", None)

    def list(self, request, *args, **kwargs):
        host = self._get_host()
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        date_range = request.query_params.get("date_range")   # optional

        # ── cards ─────────────────────────────────────────────────────────────
        total_revenue = _host_revenue(host, date_range)
        total_payout  = _host_payouts(request.user, date_range)
        balance       = _available_balance(host, request.user)   # always real-time
        next_friday   = _next_friday(date.today())

        cards = RevenueCardSerializer({
            "total_revenue":    total_revenue,
            "total_payout":     total_payout,
            "available_balance": balance,
            "next_payout_date": next_friday,
        }).data

        # ── withdrawal history (paginated) ────────────────────────────────────
        withdrawals = Withdrawal.objects.filter(
            user=request.user
        ).select_related("payout_account").order_by("-created_at")

        if date_range:
            withdrawals = _apply_date_range(withdrawals, date_range)

        page = self.paginate_queryset(withdrawals)
        items = page if page is not None else withdrawals
        history_data = WithdrawalHistorySerializer(items, many=True).data

        history = {"results": history_data}
        if page is not None:
           history.update(pagination_data(self.paginator))

        return api_response(
            message="Revenue overview retrieved successfully",
            status_code=200,
            data={"cards": cards, "withdrawal_history": history},
        )


# ── Host Withdrawal Request ────────────────────────────────────────────────────

@extend_schema(
    operation_id="host_withdrawal_request",
    request=HostWithdrawalRequestSerializer,
    parameters=[
        OpenApiParameter(
            name="Idempotency-Key",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.HEADER,
            description="Unique key to prevent duplicate requests"
        )
    ]

)
class HostWithdrawalRequestView(APIView):
    """
    POST /finance/withdraw/

    Headers
    ───────
    Idempotency-Key : <uuid>   (required — prevents duplicate submissions)

    Body
    ────
    amount            : decimal
    payout_account_id : int

    Logic
    ─────
    available = completed_order_revenue - all_non_rejected_withdrawals
    Request is only accepted when amount <= available.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_host(self):
        return getattr(self.request.user, "host_profile", None)

    def post(self, request):
        host = self._get_host()
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        # ── idempotency key ───────────────────────────────────────────────────
        idempotency_key = request.headers.get("Idempotency-Key")
        if not idempotency_key:
            return api_response(
                message="Idempotency-Key header is required.",
                status_code=400,
            )

        try:
            idempotency_uuid = uuid.UUID(str(idempotency_key))
        except ValueError:
            return api_response(
                message="Idempotency-Key must be a valid UUID.",
                status_code=400,
            )

        # ── replay detection (outside transaction — fast path) ────────────────
        existing = Withdrawal.objects.filter(
            idempotency_key=idempotency_uuid,
            user=request.user,
        ).first()
        if existing:
            return api_response(
                message="Withdrawal already submitted.",
                status_code=200,
                data={"withdrawal_id": existing.id},
            )

        # ── validate request body ─────────────────────────────────────────────
        serializer = HostWithdrawalRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)

        amount            = serializer.validated_data["amount"]
        payout_account_id = serializer.validated_data["payout_account_id"]

        # ── resolve payout account ────────────────────────────────────────────
        try:
            payout_account = PayoutInformation.objects.get(
                id=payout_account_id,
                user=request.user,
            )
        except PayoutInformation.DoesNotExist:
            return api_response(
                message="Invalid payout account.",
                status_code=400,
            )

        # ── atomic balance check + creation ───────────────────────────────────
        with transaction.atomic():
            # Lock all withdrawal rows for this user to prevent race conditions
            # where two simultaneous requests both see the same available balance.
            total_revenue = (
                Order.objects
                .filter(event__host=host, status="completed")
                .aggregate(total=Sum("total_amount"))["total"]
                or Decimal("0.00")
            )

            total_claimed = (
                Withdrawal.objects
                .select_for_update()          # row-level lock
                .filter(user=request.user)
                .exclude(status="rejected")
                .aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )

            available = max(total_revenue - total_claimed, Decimal("0.00"))

            if amount > available:
                return api_response(
                    message="Insufficient balance.",
                    status_code=400,
                    data={"available_balance": str(available)},
                )

            withdrawal = Withdrawal.objects.create(
                user=request.user,
                payout_account=payout_account,
                amount=amount,
                idempotency_key=idempotency_uuid,
            )

        return api_response(
            message="Withdrawal request submitted successfully.",
            status_code=201,
            data={
                "withdrawal_id":    str(withdrawal.id),
                "amount":           str(amount),
                "available_balance": str(available - amount),
                "status":           withdrawal.status,
            },
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
    

@extend_schema(
    operation_id="host_promo_code_list",
    parameters=[
        OpenApiParameter("event",  OpenApiTypes.UUID, description="Filter by event UUID"),
        OpenApiParameter("status", OpenApiTypes.STR,  description="active | ended"),
        OpenApiParameter("search", OpenApiTypes.STR,  description="Search by code"),
    ],
    responses=PromoCodeListSerializer(many=True),
)
class PromoCodeListView(PlanFeatureMixin,generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = PromoCodeListSerializer
    required_feature = "promo_codes"


    def list(self, request, *args, **kwargs):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        promos = PromoCodeService.get_host_promo_codes(
            host=host,
            event_id=request.query_params.get("event"),
            status=request.query_params.get("status"),
            search=request.query_params.get("search", "").strip() or None,
        )

        page  = self.paginate_queryset(promos)
        items = page if page is not None else promos
        data  = {"results": PromoCodeListSerializer(items, many=True).data}

        if page is not None:
            data.update(pagination_data(self.paginator))

        return api_response(
            message="Promo codes retrieved successfully", status_code=200, data=data
        )


# ── Promo Code Create ──────────────────────────────────────────────────────────

@extend_schema(
    operation_id="host_promo_code_create",
    request=PromoCodeCreateSerializer,
)
class PromoCodeCreateView(PlanFeatureMixin,APIView):
    permission_classes = [permissions.IsAuthenticated]
    required_feature       = "promo_codes"       # blocks free plan entirely
    check_promo_code_limit = True                   # checks limit but doesn't block — allows custom error handling

    def post(self, request):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        serializer = PromoCodeCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)

        try:
            event, promos = PromoCodeService.create_promo_code(
                host=host,
                data=serializer.validated_data,
            )
        except PromoCodeError as e:
            return api_response(message=e.message, status_code=e.status)

        return api_response(
            message="Promo code created successfully.",
            status_code=201,
            data={
                "code":                promos[0].code,
                "discount_percentage": promos[0].discount_percentage,
                "usage_limit":         promos[0].maximum_users,
                "valid_until":         promos[0].valid_till,
                "event":               event.title,
                "tickets_applied":     len(promos),
            },
        )

# ── Affiliate List ─────────────────────────────────────────────────────────────

@extend_schema(
    operation_id="host_affiliate_list",
    parameters=[
        OpenApiParameter("event",  OpenApiTypes.UUID, description="Filter by event UUID"),
        OpenApiParameter("search", OpenApiTypes.STR,  description="Search by affiliate name or email"),
    ],
    responses=AffiliateListSerializer(many=True),
)
class AffiliateListView(PlanFeatureMixin,generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AffiliateListSerializer
    required_feature = "affiliate"

    def list(self, request, *args, **kwargs):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        cards, qs = AffiliateService.get_host_affiliates(
            host=host,
            event_id=request.query_params.get("event"),
            search=request.query_params.get("search", "").strip() or None,
        )

        page  = self.paginate_queryset(list(qs))
        items = page if page is not None else list(qs)

        data = {
            "cards":   AffiliateCardSerializer(cards).data,
            "results": AffiliateListSerializer(items, many=True).data,
        }
        if page is not None:
            data.update(pagination_data(self.paginator))

        return api_response(
            message="Affiliate links retrieved successfully", status_code=200, data=data
        )






#EMAIL CAMPAIGN FEATURE VIEWS

@extend_schema(
    operation_id="host_campaign_list",
    parameters=[
        OpenApiParameter("search", OpenApiTypes.STR, description="Search by campaign name"),
    ],
    responses=EmailCampaignListSerializer(many=True),
)
class EmailCampaignListView(PlanFeatureMixin,generics.ListAPIView):
    """
    GET /campaigns/

    Lists all email campaigns for the logged-in host.
    Open rate and click rate are refreshed live from Brevo on each call
    and cached back to the DB for performance.

    Query params
    ────────────
    search : campaign name
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = EmailCampaignListSerializer
    required_feature = "email_campaigns"

    def list(self, request, *args, **kwargs):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        campaigns = CampaignService.get_host_campaigns(
            host=host,
            search=request.query_params.get("search", "").strip() or None,
        )

        page  = self.paginate_queryset(campaigns)
        items = page if page is not None else campaigns

        data = {"results": EmailCampaignListSerializer(items, many=True).data}
        if page is not None:
            data.update(pagination_data(self.paginator))

        return api_response(
            message="Campaigns retrieved successfully", status_code=200, data=data
        )


@extend_schema(
    operation_id="host_campaign_send",
    request=EmailCampaignCreateSerializer,
    responses=EmailCampaignListSerializer,
)
class EmailCampaignCreateAndSendView(APIView):
    """
    POST /campaigns/send/

    Creates and immediately sends the campaign in a single action.

    Body
    ────
    event_id      : uuid
    campaign_name : string
    subject       : string
    html_content  : string  (full HTML email body)
    sender_name   : string  (optional — defaults to event organizer name)
    sender_email  : email   (optional — defaults to event public email)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        serializer = EmailCampaignCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)

        try:
            campaign = CampaignService.create_and_send_campaign(
                host=host,
                data=serializer.validated_data,
            )
        except CampaignError as e:
            return api_response(message=e.message, status_code=e.status)

        return api_response(
            message="Campaign sent successfully.",
            status_code=201,
            data=EmailCampaignListSerializer(campaign).data,
        )

@extend_schema(
    operation_id="host_campaign_send_single",
    request=SingleEmailCampaignSerializer,
    responses={200: OpenApiResponse(description="Email sent successfully")},
)
class SingleEmailSendView(PlanFeatureMixin, APIView):
    """
    POST /campaigns/send-single/

    Sends a one-off email to a single recipient.
    Does not create a campaign record — just sends the email.

    Body
    ────
    recipient_email : email  — who to send to
    subject         : string
    html_content    : string
    sender_name     : string  (optional)
    sender_email    : email   (optional)
    """
    permission_classes = [permissions.IsAuthenticated]
    required_feature   = "email_campaigns"

    def post(self, request):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        serializer = SingleEmailCampaignSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)

        data = serializer.validated_data

        try:
            CampaignService.send_single_email(
                host=host,
                data=data,
            )
        except CampaignError as e:
            return api_response(message=e.message, status_code=e.status)

        return api_response(
            message=f"Email sent to {data['recipient_email']} successfully.",
            status_code=200,
            data={"recipient": data["recipient_email"]},
        )


#CHECK IN FEATURE VIEWS
@extend_schema(
    operation_id="checkin_overview",
    parameters=[
        OpenApiParameter("event", OpenApiTypes.UUID, description="Filter by event UUID"),
    ],
    responses=CheckInCardSerializer,
)
class CheckInOverviewView(PlanFeatureMixin,generics.ListAPIView):
    """
    GET /checkins/overview/

    Cards
    ─────
    total_tickets   : all issued tickets for host's events
    total_checkins  : successfully checked-in tickets
    issues          : duplicate or invalid scans

    Query params
    ────────────
    event : <uuid>  — scope to a single event
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = CheckInCardSerializer
    required_feature = "qr_checkin"

    def list(self, request, *args, **kwargs):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        cards = CheckInService.get_cards(
            host=host,
            event_id=request.query_params.get("event"),
        )

        return api_response(
            message="Check-in overview retrieved successfully",
            status_code=200,
            data=CheckInCardSerializer(cards).data,
        )


# ── 2. Attendee list ───────────────────────────────────────────────────────────

@extend_schema(
    operation_id="checkin_attendee_list",
    parameters=[
        OpenApiParameter("event",       OpenApiTypes.UUID, description="Filter by event UUID"),
        OpenApiParameter("ticket_type", OpenApiTypes.INT,  description="Filter by Ticket PK"),
        OpenApiParameter("status",      OpenApiTypes.STR,
                         description="pending | checked_in | duplicate | invalid"),
    ],
    responses=CheckInAttendeeSerializer(many=True),
)
class CheckInAttendeeListView(PlanFeatureMixin,generics.ListAPIView):
    """
    GET /checkins/attendees/

    Lists all issued tickets for the host's events with check-in status.
    Each row includes a signed QR token ready to embed in a QR code.

    Query params
    ────────────
    event       : <uuid>                              — filter to one event
    ticket_type : <int>                               — filter by ticket type PK
    status      : pending|checked_in|duplicate|invalid — filter by check-in status
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = CheckInAttendeeSerializer
    required_feature = "qr_checkin"

    def list(self, request, *args, **kwargs):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        qs = CheckInService.get_attendees(
            host=host,
            event_id=request.query_params.get("event"),
            ticket_type=request.query_params.get("ticket_type"),
            status=request.query_params.get("status"),
        )

        page  = self.paginate_queryset(qs)
        items = page if page is not None else list(qs)

        data = {"results": CheckInAttendeeSerializer(items, many=True).data}
        if page is not None:
            data.update(pagination_data(self.paginator))

        return api_response(
            message="Attendees retrieved successfully",
            status_code=200,
            data=data,
        )


# ── 3. QR Scan ─────────────────────────────────────────────────────────────────

@extend_schema(
    operation_id="checkin_scan",
    request=ScanInputSerializer,
    responses=ScanResultSerializer,
)
class CheckInScanView(PlanFeatureMixin,APIView):
    """
    POST /checkins/scan/

    Receives the scanned QR token, verifies it, and records the check-in.
    Always returns a clear status — never raises a 4xx on bad/duplicate scans
    so the scanning device always gets a usable response.

    Body
    ────
    token : string  — the signed token from the attendee's QR code

    Responses
    ─────────
    checked_in : first valid scan — ticket is now marked used
    duplicate  : ticket was already checked in
    invalid    : token is forged, expired, or ticket doesn't exist
    """
    # No IsAuthenticated here intentionally — scanning devices at the door
    # may use a separate auth mechanism (e.g. a dedicated scanner token).
    # Add your preferred auth when integrating with your scanner app.
    permission_classes = [permissions.IsAuthenticated]
    required_feature = "qr_checkin"

    def post(self, request):
        serializer = ScanInputSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)

        result = CheckInService.process_scan(
            token=serializer.validated_data["token"],
            scanned_by=request.user,
        )

        # Always 200 — the status field tells the scanner what happened.
        # A 4xx would cause some scanner apps to show a generic error
        # instead of the meaningful duplicate/invalid message.
        return api_response(
            message=result["message"],
            status_code=200,
            data=ScanResultSerializer(result).data,
        )




# ── Endpoint 1: Cards + Revenue Chart ─────────────────────────────────────────

@extend_schema(
    operation_id="host_dashboard_overview",
    parameters=[
        OpenApiParameter("year",  OpenApiTypes.INT, description="Year for chart e.g. 2025"),
        OpenApiParameter("month", OpenApiTypes.INT, description="Month 1-12 — daily breakdown"),
        OpenApiParameter("week",  OpenApiTypes.BOOL, description="true — current week daily breakdown"),
    ],
)
class DashboardOverviewView(generics.ListAPIView):
    """
    GET /dashboard/overview/

    Returns:
      cards       : total_revenue, tickets_sold, active_events, pending_payouts
                    each with a change indicator vs previous period
      chart       : monthly revenue for the given year (default: current year)
                    or daily if ?month= or ?week=true is passed

    Query params
    ────────────
    year  : int   — which year to show on the chart (default: current year)
    month : int   — drill into a specific month (daily buckets)
    week  : bool  — drill into the current week (daily buckets)
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = DashboardCardSerializer

    def list(self, request, *args, **kwargs):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        year  = int(request.query_params.get("year",  timezone.now().year))
        month = request.query_params.get("month")
        week  = request.query_params.get("week", "").lower() == "true"

        month = int(month) if month else None

        cards = DashboardService.get_cards(host)
        chart = DashboardService.get_revenue_chart(host, year=year, month=month, week=week)

        return api_response(
            message="Dashboard overview retrieved successfully",
            status_code=200,
            data={
                "cards": DashboardCardSerializer(cards).data,
                "chart": RevenueChartPointSerializer(chart, many=True).data,
            },
        )


# ── Endpoint 2: Activity + Notifications + Trending ───────────────────────────

@extend_schema(
    operation_id="host_dashboard_feed",
    parameters=[
        OpenApiParameter(
            "mark_read", OpenApiTypes.BOOL,
            description="true — mark all notifications as read"
        ),
    ],
)
class DashboardFeedView(generics.ListAPIView):
    """
    GET /dashboard/feed/

    Returns:
      activities    : recent host activity log (sales, check-ins, refunds, etc.)
      notifications : host notifications with read/unread status
      trending      : top 3 tickets by sales for active events

    Query params
    ────────────
    mark_read : true — marks all unread notifications as read in the same call
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = HostActivitySerializer

    def list(self, request, *args, **kwargs):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        # Optionally mark notifications read on the same request
        # so the frontend can fetch + clear badge in one call
        if request.query_params.get("mark_read", "").lower() == "true":
            DashboardService.mark_notifications_read(host)

        activities    = DashboardService.get_recent_activities(host)
        notifications = DashboardService.get_notifications(host)
        trending      = DashboardService.get_trending_tickets(host)

        # Attach revenue to trending tickets (may be None if no orders yet)
        from decimal import Decimal
        for ticket in trending:
            if ticket.revenue is None:
                ticket.revenue = Decimal("0.00")

        return api_response(
            message="Dashboard feed retrieved successfully",
            status_code=200,
            data={
                "activities":    HostActivitySerializer(activities, many=True).data,
                "notifications": HostNotificationSerializer(notifications, many=True).data,
                "trending":      TrendingTicketSerializer(trending, many=True).data,
                "follower_count":   host.following.count(),  
            },
        )




#SALES ANALYSIS 
@extend_schema(
    operation_id="sales_cards",
    parameters=[
        OpenApiParameter("date_range", OpenApiTypes.STR,  description="day | week | month"),
        OpenApiParameter("event",      OpenApiTypes.UUID, description="Filter by event UUID"),
    ],
    responses=SalesCardSerializer,
)
class SalesCardsView(APIView):
    """
    GET /sales/cards/

    7 summary cards:
      Row 1: total_revenue (+ raw change), tickets_sold,
              conversion_rate (+ % change), average_order_value (+ % change)
      Row 2: page_views, refunds, repeat_buyers

    Filters: ?date_range=day|week|month  ?event=<uuid>
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        cards = SalesCardService.get_cards(
            host=host,
            date_range=request.query_params.get("date_range"),
            event_id=request.query_params.get("event"),
        )
        return api_response(
            message="Sales cards retrieved successfully",
            status_code=200,
            data=SalesCardSerializer(cards).data,
        )


# ── Endpoint 2: Graphs ─────────────────────────────────────────────────────────

@extend_schema(
    operation_id="sales_graphs",
    parameters=[
        OpenApiParameter("event",       OpenApiTypes.UUID, description="Filter by event UUID"),
        OpenApiParameter("chart",       OpenApiTypes.STR,
                         description="Revenue chart filter: week | month | year"),
        OpenApiParameter("year",        OpenApiTypes.INT,
                         description="Year for yearly chart e.g. 2025"),
    ],
    responses=RevenuePointSerializer(many=True),
)
class SalesGraphsView(PlanFeatureMixin,APIView):
    """
    GET /sales/graphs/

    Returns 4 graph datasets in one call:
      revenue_chart  : daily or monthly revenue depending on ?chart filter
      sales_breakdown: overall % by ticket type + by time-of-day period
      week_analysis  : 7-day breakdown with morning/afternoon/evening splits
      geo_breakdown  : tickets, revenue, clicks per city + best location

    Filters
    ───────
    event : <uuid>          — scope all graphs to one event
    chart : week|month|year — revenue chart granularity
    year  : int             — used when chart=year (default current year)
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        event_id    = request.query_params.get("event")
        chart       = request.query_params.get("chart", "month")
        year        = request.query_params.get("year")
        year        = int(year) if year else timezone.now().year

        breakdown, revenue, week, geo = SalesGraphService.get_all_graphs(
            host=host,
            filter_type=chart,
            year=year,
            event_id=event_id,
            plan_slug=self.get_host_plan(),
        )

        return api_response(
            message="Sales graphs retrieved successfully",
            status_code=200,
            data={
                "sales_breakdown": SalesBreakdownSerializer(breakdown).data,
                "revenue_chart":   self.get_locked_response(
                    "revenue_chart",
                    RevenuePointSerializer(revenue, many=True).data if revenue is not None else None,
                ),
                "week_analysis":   self.get_locked_response(
                    "week_analysis",
                    WeekAnalysisSerializer(week).data if week is not None else None,
                ),
                "geo_breakdown":   self.get_locked_response(
                    "geo_breakdown",
                    GeoBreakdownSerializer(geo).data if geo is not None else None,
                ),
            },
        )


# ── Endpoint 3: Transaction History ───────────────────────────────────────────

@extend_schema(
    operation_id="sales_transactions",
    parameters=[
        OpenApiParameter("ticket_type", OpenApiTypes.INT,  description="Filter by Ticket PK"),
        OpenApiParameter("date_range",  OpenApiTypes.STR,  description="day | week | month"),
        OpenApiParameter("event",       OpenApiTypes.UUID, description="Filter by event UUID"),
        OpenApiParameter("search",      OpenApiTypes.STR,
                         description="Search by buyer name, email or event title"),
    ],
    responses=TransactionHistorySerializer(many=True),
)
class TransactionHistoryView(generics.ListAPIView):
    """
    GET /sales/transactions/

    Paginated order history with full buyer, event and ticket details.

    Filters
    ───────
    ticket_type : <int>          — filter by ticket type PK
    date_range  : day|week|month — filter by purchase date
    event       : <uuid>         — filter to one event
    search      : string         — buyer name, email or event title
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = TransactionHistorySerializer

    def list(self, request, *args, **kwargs):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        qs = TransactionService.get_transactions(
            host=host,
            ticket_type_id=request.query_params.get("ticket_type"),
            date_range=request.query_params.get("date_range"),
            search=request.query_params.get("search", "").strip() or None,
            event_id=request.query_params.get("event"),
        )

        page  = self.paginate_queryset(qs)
        items = page if page is not None else list(qs)

        data = {"results": TransactionHistorySerializer(items, many=True).data}
        if page is not None:
            data.update(pagination_data(self.paginator))

        return api_response(
            message="Transactions retrieved successfully",
            status_code=200,
            data=data,
        )



@extend_schema(
    operation_id="event_attendee_list",
    parameters=[
        OpenApiParameter(
            "event_id",
            OpenApiTypes.UUID,
            location=OpenApiParameter.PATH,
            description="UUID of the event to list attendees for",
            required=True,
        ),
        OpenApiParameter(
            "search",
            OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            description="Search by attendee name or email",
        ),
    ],
)
class DownloadEventAttendeeView(generics.ListAPIView):
    """
    GET /events/<event_id>/attendees/

    Full attendee list for a specific event owned by the logged-in host.
    Includes ticket type, amount paid, check-in status and time.

    Query params
    ────────────
    search : name or email
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = DownloadEventAttendeeSerializer

    def list(self, request, event_id=None, *args, **kwargs):
        host = _get_host(request)
        if host is None:
            return api_response(message="You are not a host.", status_code=403)

        # Validate event_id present and is a valid UUID
        if not event_id:
            return api_response(
                message="event_id is required in the URL path e.g. /events/<uuid>/attendees/",
                status_code=400,
            )

        # Verify event exists and belongs to this host
        from events.models import Event
        try:
            event = Event.objects.get(id=event_id, host=host)
        except Event.DoesNotExist:
            return api_response(
                message="Event not found or does not belong to you.",
                status_code=404,
            )

        qs = DownloadEventAttendeeService.get_attendees(
            host=host,
            event_id=event_id,
            search=request.query_params.get("search", "").strip() or None,
        )

        page  = self.paginate_queryset(qs)
        items = page if page is not None else list(qs)

        data = {
            "event":   {"id": str(event.id), "title": event.title},
            "results": DownloadEventAttendeeSerializer(items, many=True).data,
        }
        if page is not None:
            data.update(pagination_data(self.paginator))

        return api_response(
            message="Attendees retrieved successfully",
            status_code=200,
            data=data,
        )


#Gets the model from the attendde models 
@extend_schema(
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

        user = request.user
        
        deletion_request = AccountDeletionRequest.objects.create(
            user=user,
        )

        return api_response(
            "Account deletion request submitted. Admin will review it.",
            201,
            {"request_id": str(deletion_request.id)}
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
                "full_name": user.host_profile.full_name,
                "phone_number": user.host_profile.phone_number,
                "country": user.host_profile.country,
                "state": user.host_profile.state,
                "city": user.host_profile.city,
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
        name="HostActivitySharingRequestV2",
        fields={
            "show_my_events": serializers.BooleanField(required=False),
            "show_past_events": serializers.BooleanField(required=False),
        },
    ),
    responses=inline_serializer(
        name="HostActivitySharingRequestV2",
        fields={
            "show_my_events": serializers.BooleanField(),
            "show_past_events": serializers.BooleanField(),
        },
    ),
    description="Update which activity types (recent events, past event) are visible on your profile."
)
class ActivitySharingView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request):
        show_events = request.data.get("show_my_events")
        show_past_events = request.data.get("show_past_events")

        profile = request.user.host_profile

        if show_events is not None:
            profile.show_my_events = bool(show_events)
        if show_past_events is not None:
            profile.show_past_events = bool(show_past_events)

        profile.save()
        return api_response(
            "Activity sharing updated",
            200,
            {
                "show_my_events": profile.show_my_events,
                "show_past_events": profile.show_past_events
            }
        )


class PrivacySettingsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        host = Host.objects.get(user=request.user)
        serializer = PrivacySettingsSerializer(host)
        
        return api_response(
            message="Privacy settings retrieved successfully",
            status_code=200,
            data=serializer.data
        )



class HostSubscriptionStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        host = request.user.host_profile

        subscription = (
            HostSubscription.objects
            .filter(host=host)
            .select_related("plan")
            .order_by("-started_at")
            .first()
        )

        if not subscription:
            return api_response(
                message="No subscription found",
                status_code=200,
                data=None
            )

        serializer = HostSubscriptionStatusSerializer(subscription)

        return api_response(
            message="Subscription retrieved successfully",
            status_code=200,
            data=serializer.data
        )




class RenewSubscriptionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        service = RenewSubscriptionService(request.user)
        try:
            result = service.run()
            return api_response(
                message="Subscription renewed successfully",
                status_code=200,
                data=result
            )
        except SubscriptionError as e:
            # Return in your standard api_response format
            return api_response(
                message=e.message,
                status_code=e.status if hasattr(e, "status") else 400,
                data=None
            )
        except Exception as e:
            # Fallback for unexpected errors
            return api_response(
                message="An unexpected error occurred.",
                status_code=500,
                data=None
            )



class ToggleAutoRenewView(APIView):
    """
    Toggle auto-renew for the active subscription of the logged-in host.
    """
    permission_classes = [permissions.IsAuthenticated]


    @extend_schema(
        request=inline_serializer(
            name="ToggleAutoRenewRequest",
            fields={
                "auto_renew": serializers.BooleanField(
                    required=True,
                    help_text="Set to true to enable auto-renew, false to disable."
                ),
            },
        ),
        responses=inline_serializer(
            name="ToggleAutoRenewResponse",
            fields={
                "subscription_id": serializers.UUIDField(),
                "plan_slug": serializers.CharField(),
                "billing_cycle": serializers.CharField(),
                "status": serializers.CharField(),
                "expires_at": serializers.DateTimeField(),
                "currency": serializers.CharField(),
                "auto_renew": serializers.BooleanField(),
            },
        ),
        description="Enable or disable auto-renew for the active subscription."
    )
    def patch(self, request):
        host = getattr(request.user, "host_profile", None)
        if not host:
            return api_response(
                message="Host profile not found.",
                status_code=404,
                data=None
            )

        subscription = host.subscriptions.filter(status="active").last()
        if not subscription:
            return api_response(
                message="No active subscription found.",
                status_code=404,
                data=None
            )

        # Get the value from the request
        auto_renew_value = request.data.get("auto_renew")
        if auto_renew_value is None:
            return api_response(
                message="Missing 'auto_renew' field in request.",
                status_code=400,
                data=None
            )

        # Update and save
        subscription.auto_renew = bool(auto_renew_value)
        subscription.save(update_fields=["auto_renew"])

        serializer = HostSubscriptionStatusSerializer(subscription)
        return api_response(
            message=f"Auto-renew {'enabled' if subscription.auto_renew else 'disabled'} successfully.",
            status_code=200,
            data=serializer.data
        )