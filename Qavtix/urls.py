from django.contrib import admin
from django.urls import path,include
from rest_framework import permissions
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)




urlpatterns = [
    path('admin/', admin.site.urls),
    path("auth/", include("authentication.urls")),
    path("host/",include('host.urls')),
    path("public/",include('public.urls')),
    path("payments/",include('payments.urls')),
    path("attendee/",include('attendee.urls')),
    path("marketplace/",include("marketplace.urls")),

    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("swagger/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    
    
]





