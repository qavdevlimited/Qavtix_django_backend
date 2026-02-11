from django.urls import path,include
from .views import GoogleLogin
from .views import *


urlpatterns = [
    # REST auth
    path("auth/register/host/", HostRegisterView.as_view()),
    path("auth/register/attendee/", AttendeeRegisterView.as_view()),
    path("login/", CustomLoginView.as_view(), name="custom_login"),
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="token_refresh"),
    path("token/verify/", CustomTokenVerifyView.as_view(), name="token_verify"),

    path("password-reset/request/", PasswordResetOTPRequestView.as_view()),
    path("password-reset/verify-otp/", VerifyPasswordResetOTPView.as_view()),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view()),

    # Social auth
    path("social/", include("allauth.socialaccount.urls")),  # Google login
]





urlpatterns += [
    path('social/google/', GoogleLogin.as_view(), name='google_login'),
    path("social/facebook/", FacebookLogin.as_view(), name="facebook_login"),
    
]