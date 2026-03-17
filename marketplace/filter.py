import django_filters
from django.utils import timezone
from marketplace.models import MarketListing
from public.models import Category


class MarketListingFilter(django_filters.FilterSet):

    category = django_filters.ModelChoiceFilter(
        field_name="ticket__event__category",
        queryset=Category.objects.all()
    )

    event_status = django_filters.CharFilter(
        field_name="ticket__event__status"
    )

    start_date = django_filters.DateFilter(
        field_name="ticket__event__start_datetime",
        lookup_expr="date__gte"
    )

    end_date = django_filters.DateFilter(
        field_name="ticket__event__start_datetime",
        lookup_expr="date__lte"
    )

    min_price = django_filters.NumberFilter(
        field_name="price",
        lookup_expr="gte"
    )

    max_price = django_filters.NumberFilter(
        field_name="price",
        lookup_expr="lte"
    )

    past = django_filters.BooleanFilter(
        method="filter_past_events"
    )

    mine = django_filters.BooleanFilter(method="filter_mine")

    def filter_past_events(self, queryset, name, value):
        if value:
            return queryset.filter(ticket__event__start_datetime__lt=timezone.now())
        return queryset

    def filter_mine(self, queryset, name, value):
        request = getattr(self, "request", None)
        
        # If no request or user not authenticated
        if not request or not request.user.is_authenticated:
            return queryset.none() if value else queryset

        if value:
            # mine=true: only return MY listings
            return queryset.filter(seller=request.user)
        else:
            # mine=false: exclude MY listings (show others' listings)
            return queryset.exclude(seller=request.user)

    class Meta:
        model = MarketListing
        fields = [
            "category",
            "event_status",
            "start_date",
            "end_date",
            "min_price",
            "max_price",
            "past",
            "mine",
        ]