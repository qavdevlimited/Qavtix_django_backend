from dj_rest_auth.registration.views import SocialLoginView
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from rest_framework import status
from .utils import api_response
from rest_framework.exceptions import ValidationError
from django.conf import settings


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .serializers import HostRegisterSerializer, AttendeeRegisterSerializer,CustomLoginSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from drf_yasg.utils import swagger_auto_schema
from rest_framework import serializers



class CustomLoginView(APIView):

    @swagger_auto_schema(request_body=CustomLoginSerializer)
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
            

class HostRegisterView(APIView):

    @swagger_auto_schema(request_body=AttendeeRegisterSerializer)
    def post(self, request):
        serializer = HostRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        refresh = RefreshToken.for_user(user)

        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "email": user.email
        }, status=201)


class AttendeeRegisterView(APIView):

    @swagger_auto_schema(request_body=AttendeeRegisterSerializer)
    def post(self, request):
        serializer = AttendeeRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.save()
        refresh = RefreshToken.for_user(user)

        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "email": user.email
        }, status=201)