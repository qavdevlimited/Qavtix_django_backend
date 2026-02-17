from django.urls import path
from .views import *

urlpatterns = [
    path('events/create/', EventCreateView.as_view(), name='event-create'),
    path("events/<uuid:id>/update/",EventUpdateView.as_view(),name="event-update"),
    path("events/management/", EventDashboardView.as_view(), name="events-dashboard"),

]
