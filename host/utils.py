# filters.py
import django_filters
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from events.models import Event


class EventDashboardFilter(django_filters.FilterSet):

    start_date = django_filters.DateFilter(
        field_name="start_datetime", lookup_expr="date__gte"
    )

    end_date = django_filters.DateFilter(
        field_name="end_datetime", lookup_expr="date__lte"
    )

    performance = django_filters.CharFilter(method="filter_performance")

    class Meta:
        model = Event
        fields = [
            "status",
            "category",
        ]

    def filter_performance(self, queryset, name, value):
        if value == "fully_booked":
            queryset = queryset.annotate(
                total_quantity=Coalesce(Sum("tickets__quantity"), 0),
                total_sold=Coalesce(Sum("tickets__sold_quantity"), 0),
            ).filter(total_sold__gte=F("total_quantity"))

        return queryset
