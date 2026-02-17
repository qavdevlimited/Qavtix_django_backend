from django.urls import path
from .views import *

urlpatterns = [
    path('events/create/', EventCreateView.as_view(), name='event-create'),
]
