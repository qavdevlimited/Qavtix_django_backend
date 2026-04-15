# filters.py
import django_filters
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from events.models import Event
from django.utils.timezone import now as tnow ,timedelta


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
        queryset = queryset.annotate(
            total_quantity=Coalesce(Sum("tickets__quantity"), 0),
            total_sold=Coalesce(Sum("tickets__sold_count"), 0),
        )

        if value == "fully_booked":
            return queryset.filter(total_sold__gte=F("total_quantity"))

        elif value == "almost_full":
            return queryset.filter(
                total_sold__gte=F("total_quantity") * 0.8,
                total_sold__lt=F("total_quantity"),
            )

        elif value == "moderate_sales":
            return queryset.filter(
                total_sold__gte=F("total_quantity") * 0.5,
                total_sold__lt=F("total_quantity") * 0.8,
            )

        elif value == "low_sales":
            return queryset.filter(
                total_sold__gt=0,
                total_sold__lt=F("total_quantity") * 0.3,
            )

        elif value == "no_sales":
            return queryset.filter(total_sold=0)

        return queryset

        


class CustomerListFilter(django_filters.FilterSet):
    """
    Filters for the customer list endpoint.
    Applied manually against the annotated queryset (a ValuesQuerySet),
    so we define plain fields and apply them in the view.
    """
    ticket_type = django_filters.CharFilter(method="noop")   # handled in view
    date_range = django_filters.CharFilter(method="noop")     # 'day'|'week'|'month'

    class Meta:
        # No Django model — we do the filtering logic in the view helper below.
        fields = []

    def noop(self, queryset, name, value):
        return queryset


def apply_date_range(queryset, date_range_value, date_field="last_purchase_date"):
    """Return a queryset filtered to the chosen period."""
    now = tnow()
    if date_range_value == "day":
        since = now - timedelta(days=1)
    elif date_range_value == "week":
        since = now - timedelta(weeks=1)
    elif date_range_value == "month":
        since = now - timedelta(days=30)
    else:
        return queryset
    return queryset.filter(**{f"{date_field}__gte": since})


def apply_date_range_qs(queryset, date_range_value, date_field="created_at"):
    """Same helper but for ORM querysets (Order model)."""
    now = tnow()
    if date_range_value == "day":
        since = now - timedelta(days=1)
    elif date_range_value == "week":
        since = now - timedelta(weeks=1)
    elif date_range_value == "month":
        since = now - timedelta(days=30)
    else:
        return queryset
    return queryset.filter(**{f"{date_field}__gte": since})





def pagination_data(paginator):
    page = paginator.page
    return {
        "count":       page.paginator.count,
        "total_pages": page.paginator.num_pages,
        "page":        page.number,
        "next":        page.next_page_number()     if page.has_next()     else None,
        "previous":    page.previous_page_number() if page.has_previous() else None,
    }