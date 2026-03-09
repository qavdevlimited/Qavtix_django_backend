# filters.py

import django_filters
from transactions.models import IssuedTicket
from public.models import Category
from django.utils import timezone
from django_filters import rest_framework as filters
from attendee.models import FavoriteEvent
from events.models import Event
from rest_framework import generics, permissions
from public.response import api_response
from .serializers import FavoriteEventSerializer


class TicketDashboardFilter(django_filters.FilterSet):

    category = django_filters.ModelMultipleChoiceFilter(
        field_name="event__category",
        queryset=Category.objects.all()
    )

    payment = django_filters.ChoiceFilter(
        field_name="order__status",
        choices=[
            ("pending", "Pending"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("refunded", "Refunded"),
        ]
    )

    event_status = django_filters.CharFilter(
        field_name="event__status"
    )

    start_date = django_filters.DateFilter(
        field_name="event__start_datetime",
        lookup_expr="date__gte"
    )

    end_date = django_filters.DateFilter(
        field_name="event__start_datetime",
        lookup_expr="date__lte"
    )
    # Custom filters (not model fields)
    past = django_filters.BooleanFilter(
        method="filter_past_events",
        label="Past Events"
    )

    cancelled = django_filters.BooleanFilter(
        method="filter_cancelled_tickets",
        label="Cancelled Tickets"
    )
    def filter_past_events(self, queryset, name, value):
        if value:
            return queryset.filter(event__start_datetime__lt=timezone.now())
        return queryset

    def filter_cancelled_tickets(self, queryset, name, value):
        if value:
            return queryset.filter(status="cancelled")
        return queryset

    class Meta:
        model = IssuedTicket
        fields = ["category", "payment", "event_status", "past", "cancelled"]




# FilterSet for Favorite Events
class FavoriteEventFilter(django_filters.FilterSet):
    category  = django_filters.NumberFilter(
        field_name="category__id", lookup_expr="exact"
    )
    start_date = django_filters.DateFilter(
        field_name="start_datetime", lookup_expr="date__gte"
    )
    end_date = django_filters.DateFilter(
        field_name="start_datetime", lookup_expr="date__lte"
    )
    min_price = django_filters.NumberFilter(
        field_name="tickets__price", lookup_expr="gte"
    )
    max_price = django_filters.NumberFilter(
        field_name="tickets__price", lookup_expr="lte"
    )

    class Meta:
        model  = Event          # ← must match the queryset model in the view
        fields = ["category", "start_date", "end_date", "min_price", "max_price"]