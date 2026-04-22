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


from administrator.rolecontrol import RoleControlService
from transactions.models import Event, OrderTicket, Withdrawal, Order

class AdminDashboardService:

    @staticmethod
    def _payment_qs(user=None):
        """Base succeeded payments queryset, filtered by admin country if needed."""
        qs = Payment.objects.filter(status="succeeded")
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "payment")
        return qs

    @staticmethod
    def _withdrawal_qs(user=None):
        """Base withdrawal queryset, filtered by admin country if needed."""
        qs = Withdrawal.objects.all()
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "withdrawal")
        return qs

    @staticmethod
    def _user_qs(user=None):
        """User queryset filtered by country (via attendee profile)."""
        qs = User.objects.all()
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "user")
        return qs

    @staticmethod
    def _host_qs(user=None):
        """Host queryset filtered by country."""
        qs = Host.objects.all()
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "host")
        return qs

    @staticmethod
    def _event_qs(user=None):
        """Event queryset filtered by country."""
        qs = Event.objects.all()
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "event")
        return qs

    # ── helpers ──────────────────────────────────────────────
    @staticmethod
    def current_month():
        now = timezone.now()
        return now.year, now.month

    @staticmethod
    def previous_month():
        now = timezone.now()
        month = now.month - 1 or 12
        year = now.year if now.month > 1 else now.year - 1
        return year, month

    @staticmethod
    def start_of_week():
        return timezone.now() - timedelta(days=7)

    # ── section one ───────────────────────────────────────────
    @staticmethod
    def platform_revenue(user=None):
        return AdminDashboardService._payment_qs(user).aggregate(
            total=Sum("amount")
        )["total"] or 0

    @staticmethod
    def revenue_growth(user=None):
        y, m = AdminDashboardService.current_month()
        py, pm = AdminDashboardService.previous_month()
        qs = AdminDashboardService._payment_qs(user)

        current = qs.filter(
            created_at__year=y, created_at__month=m
        ).aggregate(total=Sum("amount"))["total"] or 0

        previous = qs.filter(
            created_at__year=py, created_at__month=pm
        ).aggregate(total=Sum("amount"))["total"] or 0

        if previous == 0:
            return 100
        return round(((current - previous) / previous) * 100, 2)

    @staticmethod
    def total_users(user=None):
        return AdminDashboardService._user_qs(user).count()

    @staticmethod
    def user_growth(user=None):
        y, m = AdminDashboardService.current_month()
        py, pm = AdminDashboardService.previous_month()
        qs = AdminDashboardService._user_qs(user)

        current = qs.filter(date_joined__year=y, date_joined__month=m).count()
        previous = qs.filter(date_joined__year=py, date_joined__month=pm).count()

        if previous == 0:
            return 100
        return round(((current - previous) / previous) * 100, 2)

    @staticmethod
    def transactions_today(user=None):
        today = timezone.now().date()
        return AdminDashboardService._payment_qs(user).filter(
            created_at__date=today
        ).count()

    @staticmethod
    def transactions_yesterday(user=None):
        yesterday = timezone.now().date() - timedelta(days=1)
        return AdminDashboardService._payment_qs(user).filter(
            created_at__date=yesterday
        ).count()

    @staticmethod
    def active_events(user=None):
        now = timezone.now()
        return AdminDashboardService._event_qs(user).filter(
            status="active", end_datetime__gte=now
        ).count()

    @staticmethod
    def pending_payouts(user=None):
        return AdminDashboardService._withdrawal_qs(user).filter(
            status="pending"
        ).aggregate(total=Sum("amount"))["total"] or 0

    # ── section two ───────────────────────────────────────────
    @staticmethod
    def active_users(user=None):
        y, m = AdminDashboardService.current_month()
        return AdminDashboardService._payment_qs(user).filter(
            created_at__year=y, created_at__month=m
        ).values("user").distinct().count()

    @staticmethod
    def active_hosts(user=None):
        y, m = AdminDashboardService.current_month()
        return AdminDashboardService._host_qs(user).filter(
            user__payments__status="succeeded",
            user__payments__created_at__year=y,
            user__payments__created_at__month=m,
        ).distinct().count()

    @staticmethod
    def sales_this_month(user=None):
        y, m = AdminDashboardService.current_month()
        return AdminDashboardService._payment_qs(user).filter(
            created_at__year=y, created_at__month=m
        ).aggregate(total=Sum("amount"))["total"] or 0

    # ── section three ─────────────────────────────────────────
    @staticmethod
    def users_this_week(user=None):
        start = AdminDashboardService.start_of_week()
        return AdminDashboardService._user_qs(user).filter(
            date_joined__gte=start
        ).count()

    @staticmethod
    def hosts_this_week(user=None):
        start = AdminDashboardService.start_of_week()
        return AdminDashboardService._host_qs(user).filter(
            registration_date__gte=start
        ).count()

    @staticmethod
    def events_this_week(user=None):
        start = AdminDashboardService.start_of_week()
        return AdminDashboardService._event_qs(user).filter(
            created_at__gte=start
        ).count()

    @staticmethod
    def payouts_this_week(user=None):
        start = AdminDashboardService.start_of_week()
        return AdminDashboardService._withdrawal_qs(user).filter(
            created_at__gte=start
        ).count()

    # ── main entry point ──────────────────────────────────────
    @staticmethod
    def get_dashboard(user=None, uptime_value=100):
        return {
            "section_one": {
                "platform_revenue": AdminDashboardService.platform_revenue(user),
                "revenue_growth": AdminDashboardService.revenue_growth(user),
                "total_users": AdminDashboardService.total_users(user),
                "user_growth": AdminDashboardService.user_growth(user),
                "transactions_today": AdminDashboardService.transactions_today(user),
                "transactions_yesterday": AdminDashboardService.transactions_yesterday(user),
                "active_events": AdminDashboardService.active_events(user),
                "pending_payouts": AdminDashboardService.pending_payouts(user),
                "system_uptime": uptime_value,
            },
            "section_two": {
                "active_users": AdminDashboardService.active_users(user),
                "active_sellers": AdminDashboardService.active_hosts(user),
                "sales_this_month": AdminDashboardService.sales_this_month(user),
            },
            "section_three": {
                "users_this_week": AdminDashboardService.users_this_week(user),
                "hosts_this_week": AdminDashboardService.hosts_this_week(user),
                "events_this_week": AdminDashboardService.events_this_week(user),
                "payouts_this_week": AdminDashboardService.payouts_this_week(user),
            }
        }

class ActivityService:

    @staticmethod
    def get_activities(period="week"):

        queryset = HostActivity.objects.all().order_by("-created_at")

        return queryset
    

from django.contrib.contenttypes.models import ContentType

class RevenueService:

    @staticmethod
    def _get_platform_revenue_for_period(payments, orders_in_period, featured_payments):
        """
        Platform revenue = order fees + featured event payments.
        NOT the full payment amount for orders (that belongs to the host).
        """
        order_fees = orders_in_period.aggregate(
            total=Sum("fees")
        )["total"] or 0

        featured_revenue = featured_payments.aggregate(
            total=Sum("amount")
        )["total"] or 0

        return float(order_fees + featured_revenue)

    @staticmethod
    def get_revenue(period="week", user=None):
        from django.contrib.contenttypes.models import ContentType
        from transactions.models import Order, FeaturedEvent

        # Base order queryset — completed orders only
        order_qs = Order.objects.filter(status="completed")
        if user:
            order_qs = RoleControlService.filter_by_admin(user, order_qs, "order")

        # Base featured event payments
        featured_ct = ContentType.objects.get_for_model(FeaturedEvent)
        featured_payment_qs = Payment.objects.filter(
            status="succeeded",
            content_type=featured_ct,
        )
        if user:
            featured_payment_qs = RoleControlService.filter_by_admin(
                user, featured_payment_qs, "payment"
            )

        # ── WEEK ────────────────────────────────────────────────
        if period == "week":
            days = TimeBucketFilter.get_week_days()
            result = []

            for day in days:
                day_orders = order_qs.filter(created_at__date=day)
                day_featured = featured_payment_qs.filter(created_at__date=day)

                result.append({
                    "label": day.strftime("%a"),
                    "value": RevenueService._get_platform_revenue_for_period(
                        None, day_orders, day_featured
                    )
                })

            return {"period": "week", "data": result}

        # ── MONTH ────────────────────────────────────────────────
        if period == "month":
            weeks = TimeBucketFilter.get_month_weeks()
            result = []

            for i, (start, end) in enumerate(weeks, 1):
                week_orders = order_qs.filter(
                    created_at__date__gte=start,
                    created_at__date__lt=end,
                )
                week_featured = featured_payment_qs.filter(
                    created_at__date__gte=start,
                    created_at__date__lt=end,
                )

                result.append({
                    "label": f"Week {i}",
                    "value": RevenueService._get_platform_revenue_for_period(
                        None, week_orders, week_featured
                    )
                })

            return {"period": "month", "data": result}

        # ── YEAR ─────────────────────────────────────────────────
        if period == "year":
            months = TimeBucketFilter.get_year_months()
            result = []

            for i, (start, end) in enumerate(months, 1):
                month_orders = order_qs.filter(
                    created_at__date__gte=start,
                    created_at__date__lt=end,
                )
                month_featured = featured_payment_qs.filter(
                    created_at__date__gte=start,
                    created_at__date__lt=end,
                )

                result.append({
                    "label": start.strftime("%b"),
                    "value": RevenueService._get_platform_revenue_for_period(
                        None, month_orders, month_featured
                    )
                })

            return {"period": "year", "data": result}

        return {"period": period, "data": []}


class TicketAnalyticsService:

    @staticmethod
    def get_sales_breakdown(period="week", event_id=None, user=None):
        base = OrderTicket.objects.filter(order__status="completed")

        if event_id:
            base = base.filter(order__event_id=event_id)

        # Apply RBAC — filter by the order's event's host's country
        if user:
            base = RoleControlService.filter_by_admin(user, base, "orderticket")

        # ── Date range + trunc function ──────────────────────────
        now = timezone.now()
        if period == "year":
            start_date = now - timedelta(days=365)
            trunc_func = TruncMonth("order__created_at")
        elif period == "month":
            start_date = now - timedelta(days=30)
            trunc_func = TruncWeek("order__created_at")
        else:
            start_date = now - timedelta(days=7)
            trunc_func = TruncDay("order__created_at")

        base = base.filter(order__created_at__gte=start_date)

        # ── Overall breakdown by ticket type ─────────────────────
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

        # ── Timeline breakdown ────────────────────────────────────
        timeline_data = (
            base.annotate(time_label=trunc_func)
            .values("time_label", "ticket__ticket_type")
            .annotate(count=Sum("quantity"))
            .order_by("time_label")
        )

        formatted_periods = {}
        for entry in timeline_data:
            label = entry["time_label"].strftime("%Y-%m-%d")
            if label not in formatted_periods:
                formatted_periods[label] = {"date": label, "breakdown": []}
            formatted_periods[label]["breakdown"].append({
                "ticket_type": entry["ticket__ticket_type"],
                "count": entry["count"],
            })

        return {
            "overall": overall,
            "total_sold": total_qty,
            "timeline": list(formatted_periods.values()),
        }