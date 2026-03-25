from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import timedelta
from payments.models import Payment
from transactions.models import Event, OrderTicket, Withdrawal
from host.models import Host, HostActivity
from administrator.filters import TimeBucketFilter
from collections import defaultdict
from django.contrib.auth import get_user_model
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
User = get_user_model()



class AdminDashboardService:

    
    @staticmethod
    def current_month():
        now = timezone.now()
        return now.year, now.month

    @staticmethod
    def previous_month():
        now = timezone.now()
        month = now.month - 1
        year = now.year

        if month == 0:
            month = 12
            year -= 1

        return year, month

    @staticmethod
    def start_of_week():
        return timezone.now() - timedelta(days=7)

   
    @staticmethod
    def platform_revenue():
        return Payment.objects.filter(
            status="succeeded"
        ).aggregate(total=Sum("amount"))["total"] or 0

    @staticmethod
    def revenue_growth():
        y, m = AdminDashboardService.current_month()
        py, pm = AdminDashboardService.previous_month()

        current = Payment.objects.filter(
            status="succeeded",
            created_at__year=y,
            created_at__month=m
        ).aggregate(total=Sum("amount"))["total"] or 0

        previous = Payment.objects.filter(
            status="succeeded",
            created_at__year=py,
            created_at__month=pm
        ).aggregate(total=Sum("amount"))["total"] or 0

        if previous == 0:
            return 100

        return ((current - previous) / previous) * 100

    @staticmethod
    def total_users():
        return User.objects.count()

    @staticmethod
    def user_growth():
        y, m = AdminDashboardService.current_month()
        py, pm = AdminDashboardService.previous_month()

        current = User.objects.filter(
            date_joined__year=y,
            date_joined__month=m
        ).count()

        previous = User.objects.filter(
            date_joined__year=py,
            date_joined__month=pm
        ).count()

        if previous == 0:
            return 100

        return ((current - previous) / previous) * 100

    @staticmethod
    def transactions_today():
        today = timezone.now().date()

        return Payment.objects.filter(
            status="succeeded",
            created_at__date=today
        ).count()

    @staticmethod
    def transactions_yesterday():
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)

        return Payment.objects.filter(
            status="succeeded",
            created_at__date=yesterday
        ).count()

    @staticmethod
    def active_events():
        now = timezone.now()

        return Event.objects.filter(
            status="active",
            end_datetime__gte=now
        ).count()

    @staticmethod
    def pending_payouts():
        return Withdrawal.objects.filter(
            status="pending"
        ).aggregate(total=Sum("amount"))["total"] or 0

  

    @staticmethod
    def active_users():
        y, m = AdminDashboardService.current_month()

        return Payment.objects.filter(
            status="succeeded",
            created_at__year=y,
            created_at__month=m
        ).values("user").distinct().count()

    @staticmethod
    def active_hosts():
        y, m = AdminDashboardService.current_month()

        return Host.objects.filter(
            user__payments__status="succeeded",
            user__payments__created_at__year=y,
            user__payments__created_at__month=m
        ).distinct().count()

    @staticmethod
    def sales_this_month():
        y, m = AdminDashboardService.current_month()

        return Payment.objects.filter(
            status="succeeded",
            created_at__year=y,
            created_at__month=m
        ).aggregate(total=Sum("amount"))["total"] or 0

    
   

    @staticmethod
    def users_this_week():
        start = AdminDashboardService.start_of_week()
        return User.objects.filter(date_joined__gte=start).count()

    @staticmethod
    def hosts_this_week():
        start = AdminDashboardService.start_of_week()
        return Host.objects.filter(registration_date__gte=start).count()

    @staticmethod
    def events_this_week():
        start = AdminDashboardService.start_of_week()
        return Event.objects.filter(created_at__gte=start).count()

    @staticmethod
    def payouts_this_week():
        start = AdminDashboardService.start_of_week()
        return Withdrawal.objects.filter(created_at__gte=start).count()


    @staticmethod
    def get_dashboard(uptime_value=100):
        return {
            "section_one": {
                "platform_revenue": AdminDashboardService.platform_revenue(),
                "revenue_growth": AdminDashboardService.revenue_growth(),
                "total_users": AdminDashboardService.total_users(),
                "user_growth": AdminDashboardService.user_growth(),
                "transactions_today": AdminDashboardService.transactions_today(),
                "transactions_yesterday": AdminDashboardService.transactions_yesterday(),
                "active_events": AdminDashboardService.active_events(),
                "pending_payouts": AdminDashboardService.pending_payouts(),
                "system_uptime": uptime_value,
            },
            "section_two": {
                "active_users": AdminDashboardService.active_users(),
                "active_sellers": AdminDashboardService.active_hosts(),
                "sales_this_month": AdminDashboardService.sales_this_month(),
            },
            "section_three": {
                "users_this_week": AdminDashboardService.users_this_week(),
                "hosts_this_week": AdminDashboardService.hosts_this_week(),
                "events_this_week": AdminDashboardService.events_this_week(),
                "payouts_this_week": AdminDashboardService.payouts_this_week(),
            }
        }

class ActivityService:

    @staticmethod
    def get_activities(period="week"):

        queryset = HostActivity.objects.all().order_by("-created_at")

        return queryset
    

class RevenueService:

    @staticmethod
    def get_revenue(period="week"):

        payments = Payment.objects.filter(
            status="succeeded"
        )

        #  WEEK 
        if period == "week":
            days = TimeBucketFilter.get_week_days()

            result = []

            for day in days:
                total = payments.filter(
                    created_at__date=day
                ).aggregate(total=Sum("amount"))["total"] or 0

                result.append({
                    "label": day.strftime("%a"),
                    "value": float(total)
                })

            return {
                "period": "week",
                "data": result
            }

        # MONTH 
        if period == "month":
            weeks = TimeBucketFilter.get_month_weeks()

            result = []

            for i, (start, end) in enumerate(weeks, 1):
                total = payments.filter(
                    created_at__date__gte=start,
                    created_at__date__lt=end
                ).aggregate(total=Sum("amount"))["total"] or 0

                result.append({
                    "label": f"Week {i}",
                    "value": float(total)
                })

            return {
                "period": "month",
                "data": result
            }

        #  YEAR 
        if period == "year":
            months = TimeBucketFilter.get_year_months()

            result = []

            for i, (start, end) in enumerate(months, 1):
                total = payments.filter(
                    created_at__date__gte=start,
                    created_at__date__lt=end
                ).aggregate(total=Sum("amount"))["total"] or 0

                result.append({
                    "label": start.strftime("%b"),
                    "value": float(total)
                })

            return {
                "period": "year",
                "data": result
            }

        return {"period": period, "data": []}




class TicketAnalyticsService:

    @staticmethod
    def get_sales_breakdown(period="week", event_id=None):
        base = OrderTicket.objects.filter(order__status="completed")
        if event_id:
            base = base.filter(order__event_id=event_id)

        # 1. Define Truncation and Date Range
        now = timezone.now()
        if period == "year":
            start_date = now - timedelta(days=365)
            trunc_func = TruncMonth('order__created_at')
        elif period == "month":
            start_date = now - timedelta(days=30)
            trunc_func = TruncWeek('order__created_at')
        else:  # Default to week
            start_date = now - timedelta(days=7)
            trunc_func = TruncDay('order__created_at')

        # Filter base by range
        base = base.filter(order__created_at__gte=start_date)

        # 2. Overall Breakdown (by Ticket Type)
        by_type_query = (
            base.values("ticket__ticket_type")
            .annotate(count=Sum("quantity"))
            .order_by("-count")
        )
        
        total_qty = sum(r["count"] or 0 for r in by_type_query)
        overall = [
            {
                "ticket_type": r["ticket__ticket_type"],
                "count": r["count"] or 0,
                "percentage": round((r["count"] / total_qty) * 100, 2) if total_qty else 0.0,
            }
            for r in by_type_query
        ]

        # 3. Period Breakdown (Timeline for Bar Chart)
        # Groups data by the truncated date (Day, Week, or Month)
        timeline_data = (
            base.annotate(time_label=trunc_func)
            .values("time_label", "ticket__ticket_type")
            .annotate(count=Sum("quantity"))
            .order_by("time_label")
        )

        # Reformatting timeline for frontend consumption
        # Groups the flat DB rows into: { date: [ {type: count}, ... ] }
        formatted_periods = {}
        for entry in timeline_data:
            label = entry["time_label"].strftime("%Y-%m-%d") # Format as string
            if label not in formatted_periods:
                formatted_periods[label] = {"date": label, "breakdown": []}
            
            formatted_periods[label]["breakdown"].append({
                "ticket_type": entry["ticket__ticket_type"],
                "count": entry["count"]
            })

        return {
            "overall": overall,
            "total_sold": total_qty,
            "timeline": list(formatted_periods.values())
        }