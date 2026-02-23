# filters.py

import django_filters
from transactions.models import IssuedTicket
from public.models import Category


class TicketDashboardFilter(django_filters.FilterSet):

    category = django_filters.ModelChoiceFilter(
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

    class Meta:
        model = IssuedTicket
        fields = ["category", "payment", "event_status"]