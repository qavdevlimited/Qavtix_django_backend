from django.urls import path,include
from .views import GoogleLogin
from .views import HostRegisterView, AttendeeRegisterView,CustomLoginView


urlpatterns = [
    # REST auth
    # path("", include("dj_rest_auth.urls")), 
    path("auth/register/host/", HostRegisterView.as_view()),
    path("auth/register/attendee/", AttendeeRegisterView.as_view()),
    path("login/", CustomLoginView.as_view(), name="custom_login"),

    # Social auth
    path("social/", include("allauth.socialaccount.urls")),  # Google login
]





urlpatterns += [
    path('social/google/', GoogleLogin.as_view(), name='google_login'),
    
]