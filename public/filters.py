# filters.py

import django_filters
from django_filters import rest_framework as filters
from events.models import Event, EventLocation
from public.models import Category

class EventFilter(django_filters.FilterSet):
    # Filter by category
    category = django_filters.ModelMultipleChoiceFilter(
        field_name="category",
        queryset=Event.objects.values_list("category", flat=True).distinct()
    )

    # Filter by start datetime range
    start_date = django_filters.DateFilter(
        field_name="start_datetime",
        lookup_expr="date__gte"
    )
    end_date = django_filters.DateFilter(
        field_name="start_datetime",
        lookup_expr="date__lte"
    )

    # Filter by price range
    min_price = django_filters.NumberFilter(
        field_name="tickets__price",
        lookup_expr="gte"
    )
    max_price = django_filters.NumberFilter(
        field_name="tickets__price",
        lookup_expr="lte"
    )

    # Filter by location fields (via OneToOne relation)
    city = django_filters.CharFilter(
        field_name="event_location__city",
        lookup_expr="icontains"
    )
    state = django_filters.CharFilter(
        field_name="event_location__state",
        lookup_expr="icontains"
    )
    country = django_filters.CharFilter(
        field_name="event_location__country",
        lookup_expr="icontains"
    )
    venue_name = django_filters.CharFilter(
        field_name="event_location__venue_name",
        lookup_expr="icontains"
    )

    class Meta:
        model = Event
        fields = [
            "category", "start_date", "end_date",
            "min_price", "max_price",
            "city", "state", "country", "venue_name"
        ]




class CategoryEventFilter(django_filters.FilterSet):
    category = django_filters.ModelMultipleChoiceFilter(
        field_name="category",
        queryset=Category.objects.all()  # ✅ was wrong before
    )
    start_date = django_filters.DateFilter(field_name="start_datetime", lookup_expr="date__gte")
    end_date   = django_filters.DateFilter(field_name="start_datetime", lookup_expr="date__lte")
    min_price  = django_filters.NumberFilter(field_name="tickets__price", lookup_expr="gte")
    max_price  = django_filters.NumberFilter(field_name="tickets__price", lookup_expr="lte")
    city       = django_filters.CharFilter(field_name="event_location__city",      lookup_expr="icontains")
    state      = django_filters.CharFilter(field_name="event_location__state",     lookup_expr="icontains")
    country    = django_filters.CharFilter(field_name="event_location__country",   lookup_expr="icontains")
    venue_name = django_filters.CharFilter(field_name="event_location__venue_name",lookup_expr="icontains")

    class Meta:
        model  = Event
        fields = ["category", "start_date", "end_date", "min_price", "max_price", "city", "state", "country", "venue_name"]