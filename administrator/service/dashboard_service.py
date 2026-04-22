"""
administrator/service/dashboard_service.py

Platform Revenue = Order.fees + FeaturedEvent.payment_amount
               + HostSubscription.amount_paid + AttendeeSubscription.amount_paid

All querysets respect RBAC:
  - Superadmins see everything
  - Normal admins see only their assigned country
"""

from django.db.models import Q, Sum, Count
from django.utils import timezone
from datetime import timedelta
from payments.models import Payment
from transactions.models import Event, OrderTicket, Withdrawal, Order
from host.models import Host, HostActivity
from administrator.filters import TimeBucketFilter
from django.contrib.auth import get_user_model
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
from administrator.rolecontrol import RoleControlService

User = get_user_model()


class AdminDashboardService:

    # ── Private base querysets ────────────────────────────────

    @staticmethod
    def _order_qs(user=None):
        """Completed orders filtered by admin country."""
        qs = Order.objects.filter(status="completed")
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "order")
        return qs

    @staticmethod
    def _featured_qs(user=None):
        """
        Paid featured events.
        Country scoped via event__host__country.
        Excludes admin_assignment (no money exchanged).
        """
        from transactions.models import FeaturedEvent
        qs = FeaturedEvent.objects.filter(
            status__in=["active", "expired"]
        ).exclude(payment_method="admin_assignment")

        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "featuredevent")
        return qs

    @staticmethod
    def _host_sub_qs(user=None):
        """
        Paid host subscriptions.
        Country scoped via host__country.
        """
        from host.models import HostSubscription
        qs = HostSubscription.objects.filter(
            status__in=["active", "expired", "cancelled"]
        ).exclude(plan_slug="free")

        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "hostsubscription")
        return qs

    @staticmethod
    def _attendee_sub_qs(user=None):
        """
        Paid attendee subscriptions.
        Country scoped via attendee__country.
        """
        from attendee.models import AttendeeSubscription
        qs = AttendeeSubscription.objects.filter(
            status__in=["active", "expired", "cancelled"]
        ).exclude(plan_slug="free")

        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "attendeesubscription")
        return qs

    @staticmethod
    def _withdrawal_qs(user=None):
        qs = Withdrawal.objects.all()
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "withdrawal")
        return qs

    @staticmethod
    def _host_qs(user=None):
        qs = Host.objects.all()
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "host")
        return qs

    @staticmethod
    def _event_qs(user=None):
        qs = Event.objects.all()
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "event")
        return qs

    @staticmethod
    def _user_qs(user=None):
        qs = User.objects.all()
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "user")
        return qs

    # ── Date helpers ──────────────────────────────────────────

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

    # ── Core Revenue Calculator ───────────────────────────────

    @staticmethod
    def _sum_revenue(order_qs, featured_qs, host_sub_qs, attendee_sub_qs):
        """
        Adds all 4 revenue sources together.
        Returns a single float.

        Revenue breakdown:
          - order_fees        : Qavtix fee per ticket order
          - featured_payments : Hosts pay to feature their events
          - host_sub_payments : Hosts pay for Pro/Enterprise plans
          - attendee_sub_payments: Attendees pay for Pro/Enterprise plans
        """
        order_fees = order_qs.aggregate(
            t=Sum("fees")
        )["t"] or 0

        featured_revenue = featured_qs.aggregate(
            t=Sum("payment_amount")
        )["t"] or 0

        host_sub_revenue = host_sub_qs.aggregate(
            t=Sum("amount_paid")
        )["t"] or 0

        attendee_sub_revenue = attendee_sub_qs.aggregate(
            t=Sum("amount_paid")
        )["t"] or 0

        return float(order_fees + featured_revenue + host_sub_revenue + attendee_sub_revenue)

    # ── Section One ───────────────────────────────────────────

    @staticmethod
    def platform_revenue(user=None):
        """Total all-time platform revenue from all 4 sources."""
        return AdminDashboardService._sum_revenue(
            order_qs       = AdminDashboardService._order_qs(user),
            featured_qs    = AdminDashboardService._featured_qs(user),
            host_sub_qs    = AdminDashboardService._host_sub_qs(user),
            attendee_sub_qs = AdminDashboardService._attendee_sub_qs(user),
        )

    @staticmethod
    def revenue_growth(user=None):
        """Month-over-month revenue growth across all 4 sources."""
        y, m   = AdminDashboardService.current_month()
        py, pm = AdminDashboardService.previous_month()

        def _revenue_for_month(yr, mo):
            return AdminDashboardService._sum_revenue(
                order_qs        = AdminDashboardService._order_qs(user).filter(
                    created_at__year=yr, created_at__month=mo
                ),
                featured_qs     = AdminDashboardService._featured_qs(user).filter(
                    start_date__year=yr, start_date__month=mo
                ),
                host_sub_qs     = AdminDashboardService._host_sub_qs(user).filter(
                    started_at__year=yr, started_at__month=mo
                ),
                attendee_sub_qs = AdminDashboardService._attendee_sub_qs(user).filter(
                    started_at__year=yr, started_at__month=mo
                ),
            )

        current  = _revenue_for_month(y, m)
        previous = _revenue_for_month(py, pm)

        if previous == 0:
            return 100.0
        return round(((current - previous) / previous) * 100, 2)

    @staticmethod
    def total_users(user=None):
        return AdminDashboardService._user_qs(user).count()

    @staticmethod
    def user_growth(user=None):
        y, m   = AdminDashboardService.current_month()
        py, pm = AdminDashboardService.previous_month()
        qs = AdminDashboardService._user_qs(user)

        current  = qs.filter(date_joined__year=y, date_joined__month=m).count()
        previous = qs.filter(date_joined__year=py, date_joined__month=pm).count()

        if previous == 0:
            return 100.0
        return round(((current - previous) / previous) * 100, 2)

    @staticmethod
    def transactions_today(user=None):
        """Count completed orders today."""
        today = timezone.now().date()
        return AdminDashboardService._order_qs(user).filter(
            created_at__date=today
        ).count()

    @staticmethod
    def transactions_yesterday(user=None):
        yesterday = timezone.now().date() - timedelta(days=1)
        return AdminDashboardService._order_qs(user).filter(
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

    # ── Section Two ───────────────────────────────────────────

    @staticmethod
    def active_users(user=None):
        """Users who made at least 1 completed order this month."""
        y, m = AdminDashboardService.current_month()
        return AdminDashboardService._order_qs(user).filter(
            created_at__year=y, created_at__month=m
        ).values("user").distinct().count()

    @staticmethod
    def active_hosts(user=None):
        """Hosts with at least 1 completed order against their events this month."""
        y, m = AdminDashboardService.current_month()
        return AdminDashboardService._host_qs(user).filter(
            hoster__order__status="completed",
            hoster__order__created_at__year=y,
            hoster__order__created_at__month=m,
        ).distinct().count()

    @staticmethod
    def sales_this_month(user=None):
        """Total platform revenue this month from all 4 sources."""
        y, m = AdminDashboardService.current_month()
        return AdminDashboardService._sum_revenue(
            order_qs        = AdminDashboardService._order_qs(user).filter(
                created_at__year=y, created_at__month=m
            ),
            featured_qs     = AdminDashboardService._featured_qs(user).filter(
                start_date__year=y, start_date__month=m
            ),
            host_sub_qs     = AdminDashboardService._host_sub_qs(user).filter(
                started_at__year=y, started_at__month=m
            ),
            attendee_sub_qs = AdminDashboardService._attendee_sub_qs(user).filter(
                started_at__year=y, started_at__month=m
            ),
        )

    # ── Section Three ─────────────────────────────────────────

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

    # ── Main entry point ──────────────────────────────────────

    @staticmethod
    def get_dashboard(user=None, uptime_value=100):
        return {
            "section_one": {
                "platform_revenue":      AdminDashboardService.platform_revenue(user),
                "revenue_growth":        AdminDashboardService.revenue_growth(user),
                "total_users":           AdminDashboardService.total_users(user),
                "user_growth":           AdminDashboardService.user_growth(user),
                "transactions_today":    AdminDashboardService.transactions_today(user),
                "transactions_yesterday":AdminDashboardService.transactions_yesterday(user),
                "active_events":         AdminDashboardService.active_events(user),
                "pending_payouts":       AdminDashboardService.pending_payouts(user),
                "system_uptime":         uptime_value,
            },
            "section_two": {
                "active_users":    AdminDashboardService.active_users(user),
                "active_sellers":  AdminDashboardService.active_hosts(user),
                "sales_this_month":AdminDashboardService.sales_this_month(user),
            },
            "section_three": {
                "users_this_week":  AdminDashboardService.users_this_week(user),
                "hosts_this_week":  AdminDashboardService.hosts_this_week(user),
                "events_this_week": AdminDashboardService.events_this_week(user),
                "payouts_this_week":AdminDashboardService.payouts_this_week(user),
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# Activity Service
# ─────────────────────────────────────────────────────────────────────────────

class ActivityService:

    @staticmethod
    def get_activities(user=None, period="week"):
        qs = HostActivity.objects.all().order_by("-created_at")
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "hostactivity")
        return qs


# ─────────────────────────────────────────────────────────────────────────────
# Revenue Chart Service — 4-source revenue breakdown by period
# ─────────────────────────────────────────────────────────────────────────────

class RevenueService:

    @staticmethod
    def _revenue_for_range(user, date_field_orders, date_field_featured,
                           date_field_host_sub, date_field_attendee_sub,
                           start, end):
        """
        Calculate total platform revenue for a date range from all 4 sources.
        date_field_* = the date field to filter on per model.
        """
        order_fees = AdminDashboardService._order_qs(user).filter(
            **{f"{date_field_orders}__gte": start, f"{date_field_orders}__lt": end}
        ).aggregate(t=Sum("fees"))["t"] or 0

        featured_rev = AdminDashboardService._featured_qs(user).filter(
            **{f"{date_field_featured}__gte": start, f"{date_field_featured}__lt": end}
        ).aggregate(t=Sum("payment_amount"))["t"] or 0

        host_sub_rev = AdminDashboardService._host_sub_qs(user).filter(
            **{f"{date_field_host_sub}__gte": start, f"{date_field_host_sub}__lt": end}
        ).aggregate(t=Sum("amount_paid"))["t"] or 0

        attendee_sub_rev = AdminDashboardService._attendee_sub_qs(user).filter(
            **{f"{date_field_attendee_sub}__gte": start, f"{date_field_attendee_sub}__lt": end}
        ).aggregate(t=Sum("amount_paid"))["t"] or 0

        return float(order_fees + featured_rev + host_sub_rev + attendee_sub_rev)

    @staticmethod
    def get_revenue(user=None, period="week"):
        """
        Revenue chart data from all 4 sources.
        Week → daily, Month → weekly, Year → monthly.
        """

        # ── WEEK ─────────────────────────────────────────────
        if period == "week":
            days = TimeBucketFilter.get_week_days()
            result = []
            for day in days:
                from datetime import date, timedelta as td
                start = day
                end   = day + td(days=1)
                total = RevenueService._revenue_for_range(
                    user,
                    date_field_orders       = "created_at__date",
                    date_field_featured     = "start_date__date",
                    date_field_host_sub     = "started_at__date",
                    date_field_attendee_sub = "started_at__date",
                    start=start,
                    end=end,
                )
                result.append({"label": day.strftime("%a"), "value": total})
            return {"period": "week", "data": result}

        # ── MONTH ─────────────────────────────────────────────
        if period == "month":
            weeks = TimeBucketFilter.get_month_weeks()
            result = []
            for i, (start, end) in enumerate(weeks, 1):
                total = RevenueService._revenue_for_range(
                    user,
                    date_field_orders       = "created_at__date",
                    date_field_featured     = "start_date__date",
                    date_field_host_sub     = "started_at__date",
                    date_field_attendee_sub = "started_at__date",
                    start=start,
                    end=end,
                )
                result.append({"label": f"Week {i}", "value": total})
            return {"period": "month", "data": result}

        # ── YEAR ──────────────────────────────────────────────
        if period == "year":
            months = TimeBucketFilter.get_year_months()
            result = []
            for i, (start, end) in enumerate(months, 1):
                total = RevenueService._revenue_for_range(
                    user,
                    date_field_orders       = "created_at__date",
                    date_field_featured     = "start_date__date",
                    date_field_host_sub     = "started_at__date",
                    date_field_attendee_sub = "started_at__date",
                    start=start,
                    end=end,
                )
                result.append({"label": start.strftime("%b"), "value": total})
            return {"period": "year", "data": result}

        return {"period": period, "data": []}


# ─────────────────────────────────────────────────────────────────────────────
# Ticket Analytics
# ─────────────────────────────────────────────────────────────────────────────

class TicketAnalyticsService:

    @staticmethod
    def get_sales_breakdown(user=None, period="week", event_id=None):
        base = OrderTicket.objects.filter(order__status="completed")

        if event_id:
            base = base.filter(order__event_id=event_id)

        if user:
            base = RoleControlService.filter_by_admin(user, base, "orderticket")

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

        by_type_query = (
            base.values("ticket__ticket_type")
            .annotate(count=Sum("quantity"))
            .order_by("-count")
        )

        total_qty = sum(r["count"] or 0 for r in by_type_query)
        overall = [
            {
                "ticket_type": r["ticket__ticket_type"],
                "count":       r["count"] or 0,
                "percentage":  round((r["count"] / total_qty) * 100, 2) if total_qty else 0.0,
            }
            for r in by_type_query
        ]

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
                "count":       entry["count"],
            })

        return {
            "overall":    overall,
            "total_sold": total_qty,
            "timeline":   list(formatted_periods.values()),
        }