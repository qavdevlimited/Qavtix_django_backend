from datetime import datetime, timedelta
from django.utils import timezone


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