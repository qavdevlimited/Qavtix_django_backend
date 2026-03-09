from django.shortcuts import render
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework_simplejwt.tokens import RefreshToken

from administrator.serializers import AdminLoginSerializer, AdminOTPVerifySerializer
from administrator.services import AdminAuthService, AuthError
from authentication.serializers import CustomLoginSerializer
from public.response import api_response
from rest_framework.views import APIView
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
