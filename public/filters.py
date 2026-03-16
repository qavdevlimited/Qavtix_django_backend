# filters.py

import django_filters
from django_filters import rest_framework as filters
from events.models import Event


class EventFilter(django_filters.FilterSet):
    # Filter by category ID (single or multiple)
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

    # Filter by price range (min/max)
    min_price = django_filters.NumberFilter(
        field_name="tickets__price",
        lookup_expr="gte"
    )
    max_price = django_filters.NumberFilter(
        field_name="tickets__price",
        lookup_expr="lte"
    )

    class Meta:
        model = Event
        fields = ["category", "start_date", "end_date", "min_price", "max_price"]