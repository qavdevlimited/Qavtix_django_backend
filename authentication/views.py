from dj_rest_auth.registration.views import SocialLoginView
from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from rest_framework import status
from .utils import api_response
from rest_framework.exceptions import ValidationError
from django.conf import settings





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
            