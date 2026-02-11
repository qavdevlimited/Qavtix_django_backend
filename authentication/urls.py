from django.urls import path,include
from .views import GoogleLogin
from .views import HostRegisterView, AttendeeRegisterView,CustomLoginView,CustomTokenRefreshView,CustomTokenVerifyView


urlpatterns = [
    # REST auth
    path("auth/register/host/", HostRegisterView.as_view()),
    path("auth/register/attendee/", AttendeeRegisterView.as_view()),
    path("login/", CustomLoginView.as_view(), name="custom_login"),
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="token_refresh"),
    path("token/verify/", CustomTokenVerifyView.as_view(), name="token_verify"),

    # Social auth
    path("social/", include("allauth.socialaccount.urls")),  # Google login
]





urlpatterns += [
    path('social/google/', GoogleLogin.as_view(), name='google_login'),
    
]