from django.urls import path,include
from .views import TicketDashboardView

urlpatterns = [
    path('dashboard/',TicketDashboardView.as_view(),name="attendeee_dashboard"),
]





