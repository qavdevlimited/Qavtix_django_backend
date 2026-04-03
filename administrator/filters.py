from datetime import datetime, timedelta
from django.utils import timezone
import django_filters
from django.contrib.auth import get_user_model
 
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
 