from django.shortcuts import render
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework_simplejwt.tokens import RefreshToken

from administrator.serializers import AdminHostCardSerializer, AdminHostChartPointSerializer, AdminHostDetailCardSerializer, AdminHostDetailProfileSerializer, AdminHostEventSerializer, AdminHostListSerializer, AdminHostVerificationListSerializer, AdminLoginSerializer, AdminOTPVerifySerializer, GiftBadgeSerializer, HostActivitySerializer, RevenueAnalyticsResponseSerializer, TicketAnalyticsResponseSerializer, UserDetailCardSerializer, UserDetailChartPointSerializer, UserDetailOrderSerializer, UserDetailProfileSerializer
from administrator.service.auth_service import AdminAuthService, AuthError
from administrator.service.customer_details_service import  UserDetailCardService, UserDetailOrderHistoryService, UserDetailProfileService, UserDetailSpendChartService
from administrator.service.dashboard_service import ActivityService, AdminDashboardService, RevenueService, TicketAnalyticsService
from administrator.service.host_service import AdminBadgeService, AdminHostCardService, AdminHostChartService, AdminHostDetailCardService, AdminHostDetailProfileService, AdminHostEventsService, AdminHostListService, AdminHostVerificationService
from administrator.service.uptime_service import UptimeService
from authentication.serializers import CustomLoginSerializer
from public.pagination import CustomPagination
from public.response import api_response
from rest_framework.views import APIView

from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from public.response import api_response
# administrator/views/customer_views.py

import logging
from rest_framework import generics, permissions
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes

from administrator.service.customer_service import AdminCustomerCardService, AdminCustomerListService
from administrator.service.affiliate_service import AdminAffiliateCardService, AdminAffiliateListService
from administrator.service.withdrawal_service import AdminWithdrawalListService
from administrator.serializers import (
    AdminCustomerCardSerializer,
    AdminCustomerListSerializer,
    AdminAffiliateCardSerializer,
    AdminAffiliateListSerializer,
    AdminWithdrawalListSerializer,
)
from administrator.filters import AdminCustomerFilter, AdminAffiliateFilter, AdminHostEventFilter, AdminHostFilter, AdminHostVerificationFilter, AdminWithdrawalFilter
from public.response import api_response
from public.pagination import CustomPagination
from .utils import pagination_data
from rest_framework.pagination import PageNumberPagination
from django.db.models import Sum
from rest_framework.pagination import PageNumberPagination
from django.db.models import Sum

logger = logging.getLogger(__name__)


@extend_schema(
    operation_id="admin_login",
    request=AdminLoginSerializer,
)
class AdminLoginView(APIView):
    """
    POST /admin/login/

    Step 1 of 2-factor admin login.
    Validates email + password. If correct, sends a 6-digit OTP to the
    admin's email and returns a temp_token.

    The temp_token must be submitted with the OTP in the next step.
    It expires when the OTP expires (10 minutes).

    Body
    ────
    email    : string
    password : string

    Response
    ────────
    temp_token : string  — hold this and send it with the OTP
    message    : "OTP sent to your email"
    """
    authentication_classes = []
    permission_classes     = []

    def post(self, request):
        serializer = AdminLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)

        try:
            user = AdminAuthService.verify_credentials(
                email=serializer.validated_data["email"],
                password=serializer.validated_data["password"],
            )
        except AuthError as e:
            return api_response(message=e.message, status_code=e.status)

        temp_token = AdminAuthService.generate_and_send_otp(user)

        return api_response(
            message="OTP sent to your email. It expires in 10 minutes.",
            status_code=200,
            data={"temp_token": temp_token},
        )


# ── Step 2: OTP verify → issue JWT ────────────────────────────────────────────

@extend_schema(
    operation_id="admin_otp_verify",
    request=AdminOTPVerifySerializer,
)
class AdminOTPVerifyView(APIView):
    """
    POST /admin/login/verify/

    Step 2 of 2-factor admin login.
    Submits the OTP + temp_token from Step 1.
    Returns full JWT tokens and user info on success.

    Body
    ────
    temp_token : uuid    — received from /admin/login/
    otp        : string  — 6-digit code from email

    Response
    ────────
    user   : id, email, full_name, role
    tokens : access, refresh
    """
    authentication_classes = []
    permission_classes     = []

    def post(self, request):
        serializer = AdminOTPVerifySerializer(data=request.data)
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)

        try:
            user = AdminAuthService.verify_otp(
                temp_token=str(serializer.validated_data["temp_token"]),
                otp=serializer.validated_data["otp"],
            )
        except AuthError as e:
            return api_response(message=e.message, status_code=e.status)

        # Issue JWT tokens
        refresh = RefreshToken.for_user(user)

        profile   = getattr(user, "admin_profile", None)
        full_name = profile.full_name if profile else ""
        role      = profile.role      if profile else ""

        return api_response(
            message="Login successful.",
            status_code=200,
            data={
                "user": {
                    "id":        user.id,
                    "email":     user.email,
                    "full_name": full_name,
                    "role":      role,
                },
                "tokens": {
                    "access":  str(refresh.access_token),
                    "refresh": str(refresh),
                },
            },
        )




#Dasboard Service
class AdminDashboardView(GenericAPIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        uptime = UptimeService.get_uptime()

        data = AdminDashboardService.get_dashboard(
            uptime_value=uptime
        )

        return api_response(
            message="Dashboard retrieved successfully",
            status_code=200,
            data=data
        )


class AdminRevenueView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="period",
                type=str,
                description="Time range: week | month | year",
                required=False
            )
        ],
        responses=RevenueAnalyticsResponseSerializer,
        summary="Admin Revenue Analytics",
        description="Returns total revenue and daily breakdown filtered by period (rolling window ending today)"
    )
    def get(self, request):
        period = request.query_params.get("period", "week")

        data = RevenueService.get_revenue(
            period=period
        )

        return api_response(
            message="Revenue analytics retrieved successfully",
            status_code=200,
            data=data
        )


class AdminTicketAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Ticket Analytics",
        description="Returns ticket distribution. Week groups by Day, Month by Week, Year by Month.",
        parameters=[
            OpenApiParameter(
                name="period",
                type=str,
                description="Options: week, month, year",
                required=False
            ),
            OpenApiParameter(
                name="event_id",
                type=int,
                description="Optional event ID filter",
                required=False
            )
        ]
    )
    def get(self, request):
        period = request.query_params.get("period", "week").lower()
        event_id = request.query_params.get("event_id")

        # Basic validation
        if period not in ["week", "month", "year"]:
            period = "week"

        data = TicketAnalyticsService.get_sales_breakdown(
            period=period,
            event_id=event_id
        )

        return api_response(
            message=f"Ticket analytics for the last {period} fetched successfully",
            status_code=200,
            data=data
        )


class AdminActivityView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HostActivitySerializer
    pagination_class = CustomPagination

    @extend_schema(
        summary="Admin Activity Feed",
        description="Returns recent activities (sales, refunds, check-ins, etc.)",
        parameters=[
            OpenApiParameter(
                name="period",
                type=str,
                description="week | month | year",
                required=False
            )
        ],
    )
    def get_queryset(self):
        period = self.request.query_params.get("period", "week")

        return ActivityService.get_activities(
            period=period
        )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page, many=True)

        return api_response(
            message="Activities retrieved successfully",
            status_code=200,
            data={
                **self.paginator.get_paginated_response(serializer.data).data
            }
        )



@extend_schema(
    operation_id="admin_customer_cards",
    parameters=[
        OpenApiParameter("date_range", OpenApiTypes.STR, description="day | week | month | year"),
    ],
    responses=AdminCustomerCardSerializer,
    summary="Admin Customer Cards",
    description="Returns 4 summary cards for the customer dashboard.",
)
class AdminCustomerCardsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        date_range = request.query_params.get("date_range", "month")
        cards      = AdminCustomerCardService.get_cards(date_range=date_range)

        return api_response(
            message="Customer cards retrieved successfully.",
            status_code=200,
            data=AdminCustomerCardSerializer(cards).data,
        )



# Customer List
@extend_schema(
    operation_id="admin_customer_list",
    parameters=[
        OpenApiParameter("status",           OpenApiTypes.STR,  description="active | suspended | banned | flagged"),
        OpenApiParameter("country",          OpenApiTypes.STR,  description="Filter by country"),
        OpenApiParameter("state",            OpenApiTypes.STR,  description="Filter by state"),
        OpenApiParameter("city",             OpenApiTypes.STR,  description="Filter by city"),
        OpenApiParameter("min_spend",        OpenApiTypes.NUMBER, description="Minimum total spend"),
        OpenApiParameter("max_spend",        OpenApiTypes.NUMBER, description="Maximum total spend"),
        OpenApiParameter("date_joined_from", OpenApiTypes.DATE, description="YYYY-MM-DD"),
        OpenApiParameter("date_joined_to",   OpenApiTypes.DATE, description="YYYY-MM-DD"),
        OpenApiParameter("search",           OpenApiTypes.STR,  description="Name, email or phone"),
    ],
    responses=AdminCustomerListSerializer(many=True),
    summary="Admin Customer List",
    description="Paginated list of all attendees with profile, address, spend stats and status.",
)
class AdminCustomerListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AdminCustomerListSerializer
    pagination_class   = CustomPagination
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter,filters.SearchFilter]
    filterset_class    = AdminCustomerFilter
    ordering_fields    = ["registration_date", "total_spend", "tickets_bought"]
    ordering           = ["-registration_date"]
    search_fields = ["full_name", "country","phone_number"] 

    def get_queryset(self):
        return AdminCustomerListService.get_customers(
            status           = self.request.query_params.get("status"),
            country          = self.request.query_params.get("country"),
            state            = self.request.query_params.get("state"),
            city             = self.request.query_params.get("city"),
            min_spend        = self.request.query_params.get("min_spend"),
            max_spend        = self.request.query_params.get("max_spend"),
            date_joined_from = self.request.query_params.get("date_joined_from"),
            date_joined_to   = self.request.query_params.get("date_joined_to"),
            # search           = self.request.query_params.get("search", "").strip() or None,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page     = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            
            # Use your custom pagination_data helper
            data = pagination_data(self.paginator)
            data["results"] = serializer.data
            
        else:
            serializer = self.get_serializer(queryset, many=True)
            data = {
                "results": serializer.data
            }

        return api_response(
            message="Customers retrieved successfully.",
            status_code=200,
            data=data,
        )



# Affiliate Cards


@extend_schema(
    operation_id="admin_affiliate_cards",
    parameters=[
        OpenApiParameter("date_range", OpenApiTypes.STR, description="day | week | month | year"),
    ],
    responses=AdminAffiliateCardSerializer,
    summary="Admin Affiliate Cards",
    description="Returns 4 summary cards for the affiliate dashboard.",
)
class AdminAffiliateCardsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        date_range = request.query_params.get("date_range", "month")
        cards      = AdminAffiliateCardService.get_cards(date_range=date_range)

        return api_response(
            message="Affiliate cards retrieved successfully.",
            status_code=200,
            data=AdminAffiliateCardSerializer(cards).data,
        )



# Affiliate List

@extend_schema(
    operation_id="admin_affiliate_list",
    parameters=[
        OpenApiParameter("last_activity_from", OpenApiTypes.DATE, description="YYYY-MM-DD"),
        OpenApiParameter("last_activity_to",   OpenApiTypes.DATE, description="YYYY-MM-DD"),
        OpenApiParameter("search",             OpenApiTypes.STR,  description="Name or email"),
    ],
    responses=AdminAffiliateListSerializer(many=True),
    summary="Admin Affiliate List",
    description="Paginated list of all affiliate links with performance stats.",
)
class AdminAffiliateListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AdminAffiliateListSerializer
    pagination_class   = CustomPagination
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class    = AdminAffiliateFilter
    ordering_fields    = ["last_activity", "clicks", "sales"]
    ordering           = ["-last_activity"]

    def get_queryset(self):
        return AdminAffiliateListService.get_affiliates(
            last_activity_from = self.request.query_params.get("last_activity_from"),
            last_activity_to   = self.request.query_params.get("last_activity_to"),
            search             = self.request.query_params.get("search", "").strip() or None,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page     = self.paginate_queryset(queryset)

        serializer = self.get_serializer(
            page if page is not None else queryset, 
            many=True
        )

        data = pagination_data(self.paginator) if page is not None else {}
        data["results"] = serializer.data

        return api_response(
            message="Affiliates retrieved successfully.",
            status_code=200,
            data=data,
        )


# Withdrawal History

@extend_schema(
    operation_id="admin_withdrawal_list",
    parameters=[
        OpenApiParameter("status",     OpenApiTypes.STR,    description="pending | approved | rejected | paid"),
        OpenApiParameter("date_from",  OpenApiTypes.DATE,   description="YYYY-MM-DD"),
        OpenApiParameter("date_to",    OpenApiTypes.DATE,   description="YYYY-MM-DD"),
        OpenApiParameter("min_amount", OpenApiTypes.NUMBER, description="Minimum amount"),
        OpenApiParameter("max_amount", OpenApiTypes.NUMBER, description="Maximum amount"),
        OpenApiParameter("search",     OpenApiTypes.STR,    description="Name, email or account number"),
    ],
    responses=AdminWithdrawalListSerializer(many=True),
    summary="Admin Withdrawal History",
    description="Paginated withdrawal history with profile, bank account and status.",
)
class AdminWithdrawalListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AdminWithdrawalListSerializer
    pagination_class   = CustomPagination
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class    = AdminWithdrawalFilter
    ordering_fields    = ["created_at", "amount"]
    ordering           = ["-created_at"]

    def get_queryset(self):
        return AdminWithdrawalListService.get_withdrawals(
            status     = self.request.query_params.get("status"),
            date_from  = self.request.query_params.get("date_from"),
            date_to    = self.request.query_params.get("date_to"),
            min_amount = self.request.query_params.get("min_amount"),
            max_amount = self.request.query_params.get("max_amount"),
            search     = self.request.query_params.get("search", "").strip() or None,
        )

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page     = self.paginate_queryset(queryset)

        serializer = self.get_serializer(
            page if page is not None else queryset, 
            many=True
        )

        # Consistent pagination format using your helper
        data = pagination_data(self.paginator) if page is not None else {}
        data["results"] = serializer.data

        return api_response(
            message="Withdrawal history retrieved successfully.",
            status_code=200,
            data=data,
        )





@extend_schema(
    operation_id="admin_user_detail_cards",
    parameters=[
        OpenApiParameter("date_range", OpenApiTypes.STR, description="day | week | month | year"),
    ],
    responses=UserDetailCardSerializer,
    summary="Admin User Detail — KPI Cards",
)
class AdminUserDetailCardsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request, user_id):
        date_range = request.query_params.get("date_range", "month")
        cards      = UserDetailCardService.get_cards(
            user_id=user_id,
            date_range=date_range,
        )
 
        return api_response(
            message="User KPI cards retrieved.",
            status_code=200,
            data=UserDetailCardSerializer(cards).data,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# 2. Spend Chart
# ─────────────────────────────────────────────────────────────────────────────
 
@extend_schema(
    operation_id="admin_user_detail_chart",
    parameters=[
        OpenApiParameter("date_range", OpenApiTypes.STR, description="day | week | month | year"),
    ],
    responses=UserDetailChartPointSerializer(many=True),
    summary="Admin User Detail — Spend Chart",
)
class AdminUserDetailChartView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request, user_id):
        date_range = request.query_params.get("date_range", "month")
        chart      = UserDetailSpendChartService.get_chart(
            user_id=user_id,
            date_range=date_range,
        )
 
        return api_response(
            message="Spend chart retrieved.",
            status_code=200,
            data=UserDetailChartPointSerializer(chart, many=True).data,
        )
 
 

# 3. Order History

 
@extend_schema(
    operation_id="admin_user_detail_orders",
    parameters=[
        OpenApiParameter("qty_min",    OpenApiTypes.INT,    description="Min ticket quantity per order"),
        OpenApiParameter("qty_max",    OpenApiTypes.INT,    description="Max ticket quantity per order"),
        OpenApiParameter("date_from",  OpenApiTypes.DATE,   description="Purchase date from (YYYY-MM-DD)"),
        OpenApiParameter("date_to",    OpenApiTypes.DATE,   description="Purchase date to (YYYY-MM-DD)"),
        OpenApiParameter("min_amount", OpenApiTypes.NUMBER, description="Min order amount"),
        OpenApiParameter("max_amount", OpenApiTypes.NUMBER, description="Max order amount"),
    ],
    responses=UserDetailOrderSerializer(many=True),
    summary="Admin User Detail — Order History",
)
class AdminUserDetailOrdersView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = UserDetailOrderSerializer
    pagination_class   = CustomPagination
 
    def get_queryset(self):
        user_id = self.kwargs["user_id"]
        params  = self.request.query_params
 
        return UserDetailOrderHistoryService.get_orders(
            user_id    = user_id,
            qty_min    = params.get("qty_min"),
            qty_max    = params.get("qty_max"),
            date_from  = params.get("date_from"),
            date_to    = params.get("date_to"),
            min_amount = params.get("min_amount"),
            max_amount = params.get("max_amount"),
        )
 
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)

        serializer = self.get_serializer(page if page is not None else queryset, many=True)

        data = {"results": serializer.data}

        if page is not None:
            data.update(pagination_data(self.paginator))   # Your helper function
        else:
            # Fallback when pagination is disabled
            data.update({
                "count": queryset.count(),
                "total_pages": 1,
                "page": 1,
                "next": None,
                "previous": None,
            })

        return api_response(
            message="Order history retrieved.",
            status_code=200,
            data=data,
        )
 
 

# 4. Profile Card

 
@extend_schema(
    operation_id="admin_user_detail_profile",
    responses=UserDetailProfileSerializer,
    summary="Admin User Detail — Profile Card",
)
class AdminUserDetailProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request, user_id):
        profile = UserDetailProfileService.get_profile(user_id=user_id)
 
        if not profile:
            return api_response(message="User not found.", status_code=404)
 
        return api_response(
            message="User profile retrieved.",
            status_code=200,
            data=UserDetailProfileSerializer(profile).data,
        )
 
 

# 5. Suspend / Unsuspend User

 
@extend_schema(
    operation_id="admin_user_suspend",
    request=None,
    responses={200: OpenApiResponse(description="User suspended or unsuspended")},
    summary="Admin — Suspend / Unsuspend User",
    description=(
        "Toggles user suspension. "
        "Suspended users cannot log in. "
        "Calling again on a suspended user will unsuspend them."
    ),
)
class AdminUserSuspendView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request, user_id):
        from django.contrib.auth import get_user_model
        User = get_user_model()
 
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return api_response(message="User not found.", status_code=404)
 
        # Prevent suspending other admins
        if user.is_staff or user.is_superuser:
            return api_response(
                message="Cannot suspend an admin user.",
                status_code=403,
            )
 
        if user.is_active:
            # Suspend
            user.is_active = False
            user.save(update_fields=["is_active"])
 
            logger.info(f"Admin {request.user.email} suspended user {user.email}")
 
            return api_response(
                message=f"{user.email} has been suspended.",
                status_code=200,
                data={"user_id": user_id, "is_active": False, "status": "suspended"},
            )
        else:
            # Unsuspend
            user.is_active = True
            user.save(update_fields=["is_active"])
 
            logger.info(f"Admin {request.user.email} unsuspended user {user.email}")
 
            return api_response(
                message=f"{user.email} has been unsuspended.",
                status_code=200,
                data={"user_id": user_id, "is_active": True, "status": "active"},
            )

@extend_schema(
    operation_id="admin_host_cards",
    parameters=[
        OpenApiParameter("date_range", OpenApiTypes.STR, description="day | week | month | year"),
    ],
    responses=AdminHostCardSerializer,
    summary="Admin Host Cards",
    description="4 summary KPI cards for the host management dashboard.",
)
class AdminHostCardsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request):
        date_range = request.query_params.get("date_range", "month")
        cards      = AdminHostCardService.get_cards(date_range=date_range)
 
        return api_response(
            message="Host cards retrieved successfully.",
            status_code=200,
            data=AdminHostCardSerializer(cards).data,
        )
 


@extend_schema(
    operation_id="admin_host_list",
    parameters=[
        OpenApiParameter("status",      OpenApiTypes.STR,    description="active | suspended | banned"),
        OpenApiParameter("verified",    OpenApiTypes.BOOL,   description="true | false"),
        OpenApiParameter("min_events",  OpenApiTypes.INT,    description="Min event count"),
        OpenApiParameter("max_events",  OpenApiTypes.INT,    description="Max event count"),
        OpenApiParameter("min_revenue", OpenApiTypes.NUMBER, description="Min total revenue"),
        OpenApiParameter("max_revenue", OpenApiTypes.NUMBER, description="Max total revenue"),
        OpenApiParameter("search",      OpenApiTypes.STR,    description="Name, business name or email"),
    ],
    responses=AdminHostListSerializer(many=True),
    summary="Admin Host List",
    description="Paginated list of all hosts with business info, stats and status.",
)
class AdminHostListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AdminHostListSerializer
    pagination_class   = CustomPagination
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class    = AdminHostFilter
    ordering_fields    = ["registration_date", "total_revenue", "event_count", "followers"]
    ordering           = ["-registration_date"]
 
    def get_queryset(self):
        return AdminHostListService.get_hosts(
            status      = self.request.query_params.get("status"),
            search      = self.request.query_params.get("search", "").strip() or None,
            min_events  = self.request.query_params.get("min_events"),
            max_events  = self.request.query_params.get("max_events"),
            min_revenue = self.request.query_params.get("min_revenue"),
            max_revenue = self.request.query_params.get("max_revenue"),
            verified    = self.request.query_params.get("verified"),
        )
 
    def list(self, request, *args, **kwargs):
        queryset   = self.filter_queryset(self.get_queryset())
        page       = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
 
        data = pagination_data(self.paginator) if page is not None else {}
        data["results"] = serializer.data
 
        return api_response(
            message="Host list retrieved successfully.",
            status_code=200,
            data=data,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# 3. Pending Verifications
# ─────────────────────────────────────────────────────────────────────────────
 
@extend_schema(
    operation_id="admin_host_verifications",
    parameters=[
        OpenApiParameter("status",    OpenApiTypes.STR,  description="active | suspended"),
        OpenApiParameter("date_from", OpenApiTypes.DATE, description="YYYY-MM-DD"),
        OpenApiParameter("date_to",   OpenApiTypes.DATE, description="YYYY-MM-DD"),
        OpenApiParameter("search",    OpenApiTypes.STR,  description="Name, business name or email"),
    ],
    responses=AdminHostVerificationListSerializer(many=True),
    summary="Admin Host Pending Verifications",
    description="Hosts who have submitted KYC info and are awaiting verification.",
)
class AdminHostVerificationListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AdminHostVerificationListSerializer
    pagination_class   = CustomPagination
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class    = AdminHostVerificationFilter
    ordering           = ["-registration_date"]
 
    def get_queryset(self):
        return AdminHostVerificationService.get_pending(
            search    = self.request.query_params.get("search", "").strip() or None,
            status    = self.request.query_params.get("status"),
            date_from = self.request.query_params.get("date_from"),
            date_to   = self.request.query_params.get("date_to"),
        )
 
    def list(self, request, *args, **kwargs):
        queryset   = self.filter_queryset(self.get_queryset())
        page       = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
 
        data = pagination_data(self.paginator) if page is not None else {}
        data["results"] = serializer.data
 
        return api_response(
            message="Pending verifications retrieved.",
            status_code=200,
            data=data,
        )
 
 
@extend_schema(
    operation_id="admin_host_approve",
    request=None,
    responses={200: OpenApiResponse(description="Host approved")},
    summary="Admin — Approve Host Verification",
)
class AdminHostApproveView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request, host_id):
        success, host = AdminHostVerificationService.approve(host_id)
 
        if not success:
            return api_response(message="Host not found.", status_code=404)
 
        logger.info(f"Admin {request.user.email} approved host {host_id}")
 
        return api_response(
            message=f"{host.business_name} has been verified.",
            status_code=200,
            data={"host_id": host_id, "verified": True},
        )
 
 
@extend_schema(
    operation_id="admin_host_decline",
    request=None,
    responses={200: OpenApiResponse(description="Host declined")},
    summary="Admin — Decline Host Verification",
)
class AdminHostDeclineView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request, host_id):
        success, host = AdminHostVerificationService.decline(host_id)
 
        if not success:
            return api_response(message="Host not found.", status_code=404)
 
        logger.info(f"Admin {request.user.email} declined host {host_id}")
 
        return api_response(
            message=f"{host.business_name} verification has been declined.",
            status_code=200,
            data={"host_id": host_id, "verified": False},
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# 4. Host Detail — Cards
# ─────────────────────────────────────────────────────────────────────────────
 
@extend_schema(
    operation_id="admin_host_detail_cards",
    parameters=[
        OpenApiParameter("date_range", OpenApiTypes.STR, description="day | week | month | year"),
    ],
    responses=AdminHostDetailCardSerializer,
    summary="Admin Host Detail — Earnings Cards",
)
class AdminHostDetailCardsView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request, host_id):
        date_range = request.query_params.get("date_range", "month")
        cards      = AdminHostDetailCardService.get_cards(
            host_id=host_id, date_range=date_range
        )
 
        if not cards:
            return api_response(message="Host not found.", status_code=404)
 
        return api_response(
            message="Host earnings cards retrieved.",
            status_code=200,
            data=AdminHostDetailCardSerializer(cards).data,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# 5. Host Detail — Profile
# ─────────────────────────────────────────────────────────────────────────────
 
@extend_schema(
    operation_id="admin_host_detail_profile",
    responses=AdminHostDetailProfileSerializer,
    summary="Admin Host Detail — Profile Card",
)
class AdminHostDetailProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request, host_id):
        profile = AdminHostDetailProfileService.get_profile(host_id=host_id)
 
        if not profile:
            return api_response(message="Host not found.", status_code=404)
 
        return api_response(
            message="Host profile retrieved.",
            status_code=200,
            data=AdminHostDetailProfileSerializer(profile).data,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# 6. Host Detail — Events
# ─────────────────────────────────────────────────────────────────────────────
 
@extend_schema(
    operation_id="admin_host_detail_events",
    parameters=[
        OpenApiParameter("category",    OpenApiTypes.INT,  description="Category ID"),
        OpenApiParameter("status",      OpenApiTypes.STR,  description="active | draft | cancelled | ended"),
        OpenApiParameter("event_state", OpenApiTypes.STR,  description="live | cancelled | ended"),
        OpenApiParameter("date_from",   OpenApiTypes.DATE, description="YYYY-MM-DD"),
        OpenApiParameter("date_to",     OpenApiTypes.DATE, description="YYYY-MM-DD"),
        OpenApiParameter("performance", OpenApiTypes.STR,  description="high | low"),
        OpenApiParameter("search",      OpenApiTypes.STR,  description="Event title"),
    ],
    responses=AdminHostEventSerializer(many=True),
    summary="Admin Host Detail — All Events",
)
class AdminHostDetailEventsView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class   = AdminHostEventSerializer
    pagination_class   = CustomPagination
    filter_backends    = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class    = AdminHostEventFilter
 
    def get_queryset(self):
        host_id = self.kwargs["host_id"]
        params  = self.request.query_params
 
        return AdminHostEventsService.get_events(
            host_id     = host_id,
            category    = params.get("category"),
            status      = params.get("status"),
            date_from   = params.get("date_from"),
            date_to     = params.get("date_to"),
            performance = params.get("performance"),
            event_state = params.get("event_state"),
            search      = params.get("search", "").strip() or None,
        )
 
    def list(self, request, *args, **kwargs):
        queryset   = self.filter_queryset(self.get_queryset())
        page       = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page if page is not None else queryset, many=True)
 
        data = pagination_data(self.paginator) if page is not None else {}
        data["results"] = serializer.data
 
        return api_response(
            message="Host events retrieved.",
            status_code=200,
            data=data,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# 7. Host Detail — Revenue / Ticket Chart
# ─────────────────────────────────────────────────────────────────────────────
 
@extend_schema(
    operation_id="admin_host_detail_chart",
    parameters=[
        OpenApiParameter("chart_type", OpenApiTypes.STR, description="revenue | tickets"),
        OpenApiParameter("year",       OpenApiTypes.INT, description="e.g. 2026"),
        OpenApiParameter("month",      OpenApiTypes.INT, description="1-12 — returns daily if provided"),
    ],
    responses=AdminHostChartPointSerializer(many=True),
    summary="Admin Host Detail — Revenue / Ticket Chart",
)
class AdminHostDetailChartView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def get(self, request, host_id):
        chart_type = request.query_params.get("chart_type", "revenue")
        year       = request.query_params.get("year")
        month      = request.query_params.get("month")
 
        chart = AdminHostChartService.get_chart(
            host_id    = host_id,
            chart_type = chart_type,
            year       = year,
            month      = month,
        )
 
        return api_response(
            message="Chart data retrieved.",
            status_code=200,
            data=AdminHostChartPointSerializer(chart, many=True).data,
        )
 
 
# ─────────────────────────────────────────────────────────────────────────────
# 8. Suspend Host
# ─────────────────────────────────────────────────────────────────────────────
 
@extend_schema(
    operation_id="admin_host_suspend",
    request=None,
    responses={200: OpenApiResponse(description="Host suspended or unsuspended")},
    summary="Admin — Suspend / Unsuspend Host",
    description="Toggles host user suspension. Calling again unsuspends.",
)
class AdminHostSuspendView(APIView):
    permission_classes = [permissions.IsAuthenticated]
 
    def post(self, request, host_id):
        from host.models import Host
        from django.contrib.auth import get_user_model
        User = get_user_model()
 
        try:
            host = Host.objects.select_related("user").get(id=host_id)
        except Host.DoesNotExist:
            return api_response(message="Host not found.", status_code=404)
 
        user = host.user
 
        if user.is_staff or user.is_superuser:
            return api_response(
                message="Cannot suspend an admin user.",
                status_code=403,
            )
 
        if user.is_active:
            user.is_active = False
            user.save(update_fields=["is_active"])
            logger.info(f"Admin {request.user.email} suspended host {host_id}")
            return api_response(
                message=f"{host.business_name} has been suspended.",
                status_code=200,
                data={"host_id": host_id, "is_active": False, "status": "suspended"},
            )
        else:
            user.is_active = True
            user.save(update_fields=["is_active"])
            logger.info(f"Admin {request.user.email} unsuspended host {host_id}")
            return api_response(
                message=f"{host.business_name} has been unsuspended.",
                status_code=200,
                data={"host_id": host_id, "is_active": True, "status": "active"},
            )



class GiftBadgeView(APIView):

    @extend_schema(
        request=None,
        responses={200: None}
    )
    def post(self, request, host_id):

        result = AdminBadgeService.gift_badge(host_id=host_id)

        if "error" in result:
            return api_response(
                message=result["error"],
                status_code=400,
                data=None,
            )

        return api_response(
            message="Badge gifted successfully",
            status_code=200,
            data=result,
        )