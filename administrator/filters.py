from datetime import datetime, timedelta
from django.utils import timezone
import django_filters
from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
 
User = get_user_model()



class TimeBucketFilter:

    @staticmethod
    def get_week_days():
        """
        Returns last 7 days including today
        """
        today = timezone.now().date()
        return [(today - timedelta(days=i)) for i in range(6, -1, -1)]

    @staticmethod
    def get_month_weeks():
        """
        Returns 4 weekly buckets for current month
        """
        today = timezone.now().date()

        start_of_month = today.replace(day=1)

        return [
            (start_of_month + timedelta(days=i * 7),
             start_of_month + timedelta(days=(i + 1) * 7))
            for i in range(4)
        ]

    @staticmethod
    def get_year_months():
        """
        Returns 12 months of current year
        """
        year = timezone.now().year

        return [
            (datetime(year, m, 1).date(),
             datetime(year, m + 1, 1).date() if m < 12 else datetime(year, 12, 31).date())
            for m in range(1, 13)
        ]


class AdminCustomerFilter(django_filters.FilterSet):
    """
    Filter for admin customer list.
    All filters are optional and combinable.
    """
    status         = django_filters.CharFilter(method="filter_status")
    country        = django_filters.CharFilter(field_name="country", lookup_expr="iexact")
    state          = django_filters.CharFilter(field_name="state",   lookup_expr="iexact")
    city           = django_filters.CharFilter(field_name="city",    lookup_expr="iexact")
    min_spend      = django_filters.NumberFilter(method="filter_min_spend")
    max_spend      = django_filters.NumberFilter(method="filter_max_spend")
    date_joined_from = django_filters.DateFilter(field_name="registration_date", lookup_expr="date__gte")
    date_joined_to   = django_filters.DateFilter(field_name="registration_date", lookup_expr="date__lte")
    # search         = django_filters.CharFilter(method="filter_search")
 
    def filter_status(self, queryset, name, value):
        from administrator.service.customer_service import AdminCustomerListService
        if value == "active":
            return queryset.filter(user__is_active=True)
        elif value in ("suspended", "banned"):
            return queryset.filter(user__is_active=False)
        elif value == "flagged":
            flagged_ids = AdminCustomerListService._get_flagged_user_ids()
            return queryset.filter(user_id__in=flagged_ids)
        return queryset
 
    def filter_min_spend(self, queryset, name, value):
        return queryset.filter(total_spend__gte=value)
 
    def filter_max_spend(self, queryset, name, value):
        return queryset.filter(total_spend__lte=value)
 
    # def filter_search(self, queryset, name, value):
    #     from django.db.models import Q
    #     return queryset.filter(
    #         Q(full_name__icontains=value) |
    #         Q(user__email__icontains=value) |
    #         Q(phone_number__icontains=value)
    #     )
 
    class Meta:
        from attendee.models import Attendee
        model  = Attendee
        fields = [
            "status", "country", "state", "city",
            "min_spend", "max_spend",
            "date_joined_from", "date_joined_to"
        ]
 
 
class AdminAffiliateFilter(django_filters.FilterSet):
    """Filter for admin affiliate list."""
    last_activity_from = django_filters.DateFilter(method="filter_activity_from")
    last_activity_to   = django_filters.DateFilter(method="filter_activity_to")
    search             = django_filters.CharFilter(method="filter_search")
 
    last_activity_from = django_filters.DateFilter(
        field_name='updated_at',
        lookup_expr='date__gte'
    )
    last_activity_to = django_filters.DateFilter(
        field_name='updated_at',
        lookup_expr='date__lte'
    )
 
    def filter_search(self, queryset, name, value):
        from django.db.models import Q
        return queryset.filter(
            Q(user__attendee_profile__full_name__icontains=value) |
            Q(user__email__icontains=value)
        )
 
    class Meta:
        from attendee.models import AffiliateLink
        model  = AffiliateLink
        fields = ["last_activity_from", "last_activity_to", "search"]
 
 
class AdminWithdrawalFilter(django_filters.FilterSet):
    """Filter for admin withdrawal history."""
    status     = django_filters.CharFilter(field_name="status", lookup_expr="iexact")
    date_from  = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to    = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")
    min_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="gte")
    max_amount = django_filters.NumberFilter(field_name="amount", lookup_expr="lte")
    search     = django_filters.CharFilter(method="filter_search")
 
    def filter_search(self, queryset, name, value):
        from django.db.models import Q
        return queryset.filter(
            Q(user__attendee_profile__full_name__icontains=value) |
            Q(user__email__icontains=value) |
            Q(payout_account__account_number__icontains=value)
        )
 
    class Meta:
        from transactions.models import Withdrawal
        model  = Withdrawal
        fields = ["status", "date_from", "date_to", "min_amount", "max_amount", "search"]
 



class AdminHostFilter(django_filters.FilterSet):
    status      = django_filters.CharFilter(method="filter_status")
    verified    = django_filters.BooleanFilter(field_name="verified")
    min_events  = django_filters.NumberFilter(method="filter_min_events")
    max_events  = django_filters.NumberFilter(method="filter_max_events")
    min_revenue = django_filters.NumberFilter(method="filter_min_revenue")
    max_revenue = django_filters.NumberFilter(method="filter_max_revenue")
    search      = django_filters.CharFilter(method="filter_search")
 
    def filter_status(self, queryset, name, value):
        if value == "active":
            return queryset.filter(user__is_active=True)
        elif value in ("suspended", "banned"):
            return queryset.filter(user__is_active=False)
        return queryset
 
    def filter_min_events(self, queryset, name, value):
        return queryset.filter(event_count__gte=value)
 
    def filter_max_events(self, queryset, name, value):
        return queryset.filter(event_count__lte=value)
 
    def filter_min_revenue(self, queryset, name, value):
        return queryset.filter(total_revenue__gte=value)
 
    def filter_max_revenue(self, queryset, name, value):
        return queryset.filter(total_revenue__lte=value)
 
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(full_name__icontains=value)     |
            Q(business_name__icontains=value) |
            Q(user__email__icontains=value)   |
            Q(phone_number__icontains=value)
        )
 
    class Meta:
        from host.models import Host
        model  = Host
        fields = [
            "status", "verified",
            "min_events", "max_events",
            "min_revenue", "max_revenue",
            "search",
        ]
 
 
class AdminHostVerificationFilter(django_filters.FilterSet):
    status    = django_filters.CharFilter(method="filter_status")
    date_from = django_filters.DateFilter(field_name="registration_date", lookup_expr="date__gte")
    date_to   = django_filters.DateFilter(field_name="registration_date", lookup_expr="date__lte")
    search    = django_filters.CharFilter(method="filter_search")
 
    def filter_status(self, queryset, name, value):
        if value == "active":
            return queryset.filter(user__is_active=True)
        elif value in ("suspended", "banned"):
            return queryset.filter(user__is_active=False)
        return queryset
 
    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(full_name__icontains=value)     |
            Q(business_name__icontains=value) |
            Q(user__email__icontains=value)
        )
 
    class Meta:
        from host.models import Host
        model  = Host
        fields = ["status", "date_from", "date_to", "search"]
 
 
class AdminHostEventFilter(django_filters.FilterSet):
    category    = django_filters.NumberFilter(field_name="category_id")
    status      = django_filters.CharFilter(field_name="status", lookup_expr="iexact")
    event_state = django_filters.CharFilter(method="filter_event_state")
    date_from   = django_filters.DateFilter(field_name="start_datetime", lookup_expr="date__gte")
    date_to     = django_filters.DateFilter(field_name="start_datetime", lookup_expr="date__lte")
    performance = django_filters.CharFilter(method="filter_performance")
    search      = django_filters.CharFilter(field_name="title", lookup_expr="icontains")
 
    def filter_event_state(self, queryset, name, value):
        from django.utils import timezone
        now = timezone.now()
        if value == "live":
            return queryset.filter(
                start_datetime__lte=now, end_datetime__gte=now, status="active"
            )
        elif value == "cancelled":
            return queryset.filter(status="cancelled")
        elif value == "ended":
            return queryset.filter(end_datetime__lt=now)
        return queryset
 
    def filter_performance(self, queryset, name, value):
        from django.db.models import F
        if value == "high":
            return queryset.order_by(F("revenue").desc(nulls_last=True))
        elif value == "low":
            return queryset.order_by(F("revenue").asc(nulls_last=True))
        return queryset
 
    class Meta:
        from events.models import Event
        model  = Event
        fields = ["category", "status", "event_state", "date_from", "date_to", "performance", "search"]
 