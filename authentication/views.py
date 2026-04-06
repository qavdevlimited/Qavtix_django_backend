from dj_rest_auth.registration.views import SocialLoginView
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.facebook.views import FacebookOAuth2Adapter
from allauth.socialaccount.providers.apple.views import AppleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from rest_framework import status
from .utils import api_response,generate_otp
from rest_framework.exceptions import ValidationError
from django.conf import settings


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import HostRegisterSerializer, AttendeeRegisterSerializer,CustomLoginSerializer,ForgotPasswordSerializer,VerifyPasswordResetOTPSerializer,PasswordResetConfirmSerializer
from rest_framework_simplejwt.tokens import RefreshToken,TokenError,AccessToken
from rest_framework import serializers
from django.utils import timezone
from datetime import timedelta
from .models import PasswordResetOTP, PasswordResetToken
from notification.utils import send_password_reset_otp
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from drf_spectacular.utils import extend_schema


@extend_schema(
    request=CustomLoginSerializer,
)
class CustomLoginView(APIView):
    
    def post(self, request):
        serializer = CustomLoginSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except serializers.ValidationError as e:
            return api_response(
                message=e.detail[0] if isinstance(e.detail, list) else str(e.detail),
                status_code=status.HTTP_400_BAD_REQUEST,
                data={}
            )

        user = serializer.validated_data['user']
        refresh = RefreshToken.for_user(user)

        # Get full_name and role from profile
        if hasattr(user, 'attendee_profile'):
            profile = user.attendee_profile
        elif hasattr(user, 'host_profile'):
            profile = user.host_profile
        else:
            profile = None

        full_name = profile.full_name if profile else ''
        role = profile.role if profile else ''

        response_data = {
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": full_name,
                "role": role
            },
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh)
            }
        }

        return api_response(
            message="Login successful",
            status_code=status.HTTP_200_OK,
            data=response_data
        )

    
class FacebookLogin(SocialLoginView):
    adapter_class = FacebookOAuth2Adapter
    client_class = OAuth2Client
    callback_url = settings.FACEBOOK_CALLBACK_URL

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            return api_response("Login successful", status.HTTP_200_OK, response.data)
        except ValidationError as e:
            # Flatten DRF validation errors
            return api_response(e, status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return api_response(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)

class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    client_class = OAuth2Client
    callback_url = settings.CALLBACK_URL


    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            return api_response("Login successful", status.HTTP_200_OK, response.data)
        except ValidationError as e:
            # Flatten DRF validation errors
            return api_response(e, status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return api_response(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class AppleLogin(SocialLoginView):
    adapter_class = AppleOAuth2Adapter
    client_class = OAuth2Client
    callback_url = settings.CALLBACK_URL

    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            return api_response("Login successful", status.HTTP_200_OK, response.data)
        except ValidationError as e:
            return api_response(e, status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return api_response(str(e), status.HTTP_500_INTERNAL_SERVER_ERROR)
            

@extend_schema(
    request=HostRegisterSerializer,
)
class HostRegisterView(APIView):

    def post(self, request):
        serializer = HostRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        refresh = RefreshToken.for_user(user)

        return api_response(
            message="Registration Successful",
            status_code=status.HTTP_201_CREATED,
            data={
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "email": user.email
            }
        )


@extend_schema(
    request=AttendeeRegisterSerializer,
)
class AttendeeRegisterView(APIView):

    def post(self, request):
        serializer = AttendeeRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        refresh = RefreshToken.for_user(user)


        return api_response(
                message="Registration Successful",
                status_code=status.HTTP_201_CREATED,
                data={"access": str(refresh.access_token),
                "refresh": str(refresh),
                "email": user.email}
            )
    


class CustomTokenRefreshView(APIView):
    """
    Refresh access token using a valid refresh token
    """
    def post(self, request):
        refresh_token = request.data.get("refresh")

        if not refresh_token:
            return api_response(
                message="Refresh token is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            refresh = RefreshToken(refresh_token)
            new_access = str(refresh.access_token)
        except TokenError:
            return api_response(
                message="Invalid or expired refresh token",
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        return api_response(
            message="Token refreshed successfully",
            status_code=status.HTTP_200_OK,
            data={"access": new_access}
        )
    

class CustomTokenVerifyView(APIView):
    """
    Verify if access token is valid
    """
    def post(self, request):
        token = request.data.get("token")

        if not token:
            return api_response(
                message="Token is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        try:
            AccessToken(token)
        except TokenError:
            return api_response(
                message="Invalid or expired token",
                status_code=status.HTTP_401_UNAUTHORIZED
            )

        return api_response(
            message="Token is valid",
            status_code=status.HTTP_200_OK
        )



@extend_schema(
    request=ForgotPasswordSerializer,
)
class PasswordResetOTPRequestView(APIView):
    permission_classes = []

    def post(self, request):
        email = request.data.get("email")

        response = {
            "message": "If an account with this email exists, an OTP will be sent."
        }

        try:
            user = User.objects.get(email=email)

            # Invalidate old OTPs
            PasswordResetOTP.objects.filter(
                user=user,
                used=False
            ).update(used=True)

            otp = generate_otp(settings.PASSWORD_RESET_OTP_LENGTH)

            PasswordResetOTP.objects.create(
                user=user,
                code=otp,
                expires_at=timezone.now()
                + timedelta(minutes=settings.PASSWORD_RESET_OTP_TTL_MINUTES)
            )

            send_password_reset_otp(user.email, otp)

        except User.DoesNotExist:
            pass

        return Response(response)


@extend_schema(
    request=VerifyPasswordResetOTPSerializer,
)
class VerifyPasswordResetOTPView(APIView):
    permission_classes = []

    def post(self, request):
        email = request.data.get("email")
        otp = request.data.get("otp").strip()

        try:
            user = User.objects.get(email=email)

            otp_obj = PasswordResetOTP.objects.get(
                user=user,
                code=otp,
                used=False
            )

            if otp_obj.is_expired():
                return Response({"message": "OTP expired"}, status=400)

            # Mark OTP as used
            otp_obj.used = True
            otp_obj.save()

            # Invalidate previous tokens
            PasswordResetToken.objects.filter(
                user=user,
                used=False
            ).update(used=True)

            # Create reset token
            reset_token = PasswordResetToken.objects.create(
                user=user,
                expires_at=timezone.now()
                + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_TTL_MINUTES)
            )

            return Response({
                "reset_token": str(reset_token.token),
                "expires_in": settings.PASSWORD_RESET_TOKEN_TTL_MINUTES * 60
            })

        except (User.DoesNotExist, PasswordResetOTP.DoesNotExist):
            return Response(
                {"message": "Invalid OTP"},
                status=400
            )


@extend_schema(
    request=PasswordResetConfirmSerializer,
)
class PasswordResetConfirmView(APIView):
    permission_classes = []

    def post(self, request):
        token = request.data.get("token")
        new_password = request.data.get("new_password")

        try:
            reset_token = PasswordResetToken.objects.get(
                token=token,
                used=False
            )

            if reset_token.is_expired():
                return Response(
                    {"message": "Reset token expired"},
                    status=400
                )

            user = reset_token.user

            user.set_password(new_password)
            user.save()

            reset_token.used = True
            reset_token.save()

            return Response({"message": "Password reset successful"})

        except PasswordResetToken.DoesNotExist:
            return Response(
                {"message": "Invalid reset token"},
                status=400
            )
