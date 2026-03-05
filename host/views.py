from decimal import Decimal
import uuid

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.views import APIView
from attendee.models import Attendee
from events.models import Event
from host.helpers import _apply_date_range, _available_balance, _base_orders, _host_orders, _host_payouts, _host_revenue, _next_friday, _pct_change, _period_delta
from payments.models import PayoutInformation
from transactions.models import Order, OrderTicket, Withdrawal
from .serializers import AttendeeProfileSerializer, CustomerDetailCardSerializer, CustomerListSerializer, CustomerListSerializer, CustomerOrderHistorySerializer, EventSerializer,EventCardSerializer,EventTableSerializer, HostWithdrawalRequestSerializer, PayoutInformationSerializer, RevenueCardSerializer, RevenueChartPointSerializer, WithdrawalHistorySerializer
from public.response import flatten_errors,api_response
from django.http import Http404
from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.http import Http404
from .utils import EventDashboardFilter, apply_date_range_qs
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

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes



class EventCreateView(generics.CreateAPIView):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        # pass request to serializer so it can access user
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context
   
    def create(self, request, *args, **kwargs):
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

        return Event.objects.filter(host=user.host_profile)

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
                    "count": self.paginator.page.paginator.count,
                    "next": self.paginator.get_next_link(),
                    "previous": self.paginator.get_previous_link(),
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
class CustomerListView(generics.ListAPIView):
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
            data["count"]    = self.paginator.page.paginator.count
            data["next"]     = self.paginator.get_next_link()
            data["previous"] = self.paginator.get_previous_link()

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
class CustomerDetailView(generics.ListAPIView):
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
            history["count"]    = self.paginator.page.paginator.count
            history["next"]     = self.paginator.get_next_link()
            history["previous"] = self.paginator.get_previous_link()

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
