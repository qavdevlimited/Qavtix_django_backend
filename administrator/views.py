from django.shortcuts import render
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework_simplejwt.tokens import RefreshToken

from administrator.serializers import AdminLoginSerializer, AdminOTPVerifySerializer, HostActivitySerializer, RevenueAnalyticsResponseSerializer, TicketAnalyticsResponseSerializer
from administrator.services import AdminAuthService, AuthError
from administrator.service.dashboard_service import ActivityService, AdminDashboardService, RevenueService, TicketAnalyticsService
from administrator.service.uptime_service import UptimeService
from authentication.serializers import CustomLoginSerializer
from public.pagination import CustomPagination
from public.response import api_response
from rest_framework.views import APIView

from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from public.response import api_response
# Create your views here.


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