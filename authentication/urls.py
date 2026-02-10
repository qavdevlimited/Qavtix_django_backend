from django.urls import path,include
from .views import GoogleLogin


urlpatterns = [
    # REST auth
    path("", include("dj_rest_auth.urls")),  # login/logout/password reset
    path("registration/", include("dj_rest_auth.registration.urls")),  # register

    # Social auth
    path("social/", include("allauth.socialaccount.urls")),  # Google login
]





urlpatterns += [
    path('social/google/', GoogleLogin.as_view(), name='google_login'),
    
]