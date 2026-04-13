from decimal import Decimal
from datetime import timedelta
from django.db.models import Count, Sum, Q
from django.utils import timezone

from events.models import Ticket, PromoCode,Event
from attendee.models import AffiliateLink          # adjust to your path
from host.models import CheckIn, HostActivity, HostNotification
from payments.models import PaymentCard
from transactions.models import IssuedTicket, Order, OrderTicket

from django.core import signing
from django.db import transaction

from transactions.models import IssuedTicket
from host.models import CheckIn
from host.helpers import _apply_day_range, _pct_change, verify_checkin_token

from django.db.models import Sum, Count, Q, Avg, F
from django.db.models.functions import TruncDay, TruncMonth


from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum
from django.contrib.auth import get_user_model

from transactions.models import  Order, Withdrawal
from ..models import Host

User = get_user_model()


class HostService:

    @staticmethod
    def get_host_profile(user):
        """
        Returns host profile data + balance + payout availability
        """
        try:
            host = Host.objects.select_related('user').prefetch_related(
                'subscriptions', 'gifted_badges'
            ).get(user=user)
            is_host = True
        except Host.DoesNotExist:
            host = None
            is_host = False

        data = {
            "is_host": is_host,
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": getattr(user, 'full_name', user.get_full_name() or user.username),
            }
        }

        if not is_host:
            data["message"] = "You do not have a host profile yet. Please complete host registration."
            data["payout_available"] = False
            data["balance"] = {
                "available_balance": "0.00",
                "payout_available": False
            }
            data["subscription"] = False
            data["verified_badge"] = False
            return data

        # Host exists - get full profile
        from ..serializers import HostProfileSerializer
        serializer = HostProfileSerializer(host)

        data["host"] = serializer.data
        data["host"]["currency"] = HostService.get_host_currency(host)

        # === Subscription: True only if active + paid (not free) ===
        data["subscription"] = HostService.has_active_paid_subscription(host)

        # Verified Badge
        data["verified_badge"] = HostService.has_active_verified_badge(host)

        # Calculate balance and payout status
        payout_available, available_balance = HostService.calculate_balance_and_payout(user)

        data["payout_available"] = payout_available
        data["available_balance"] = available_balance

        eligible, message = HostService.can_activate_free_trial(host)
        data["can_activate_free_trial"] = eligible

        return data

    @staticmethod
    def get_host_currency(host):
        """Get currency for host"""
        try:
            from payments.services.currency_utils import get_currency_for_host
            return get_currency_for_host(host)
        except Exception:
            return "NGN"

    @staticmethod
    def has_active_paid_subscription(host):
        """
        Returns True only if the host has an ACTIVE subscription 
        that is NOT the free plan.
        """
        return host.subscriptions.filter(
            status="active",
            billing_cycle__in=["monthly", "annual"]   # exclude "free"
        ).exists()

    @staticmethod
    def has_active_verified_badge(host):
        """Check if host has an active verified badge"""
        return host.gifted_badges.filter(is_active=True).exists()

    @staticmethod
    def calculate_balance_and_payout(user):
        """
        Calculate host earnings, withdrawals and payout availability.
        Payout available ONLY when:
        - Available balance >= 10,000
        - Today is Friday
        """
        # Total earnings from normal (non-marketplace) completed orders
        normal_earnings = Order.objects.filter(
            event__host=user.host_profile,
            status="completed",
            marketplace_listing__isnull=True
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')

        # Total amount successfully withdrawn (approved or paid)
        total_withdrawn = Withdrawal.objects.filter(
            user=user,
            status__in=["approved", "paid"]
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        available_balance = normal_earnings - total_withdrawn

        # Check if today is Friday
        today = timezone.now().date()
        is_friday = today.weekday() == 4

        payout_available = (available_balance >= Decimal('10000')) and is_friday

        return payout_available,available_balance


    @staticmethod
    def can_activate_free_trial(host):
        """
        Returns True/False + reason (for FE to show proper message)
        Optimized - minimal queries, no N+1.
        """
        if not host:
            return False, "You need to create a host profile first."

        # Use the same queryset to avoid multiple hits
        subscriptions_qs = host.subscriptions.all()

        # 1. Already has active paid plan?
        has_active_paid = subscriptions_qs.filter(
            status="active",
            billing_cycle__in=["monthly", "annual"]
        ).exists()

        if has_active_paid:
            return False, "You already have an active paid subscription."

        # 2. Has ever paid for any plan before?
        has_paid_before = subscriptions_qs.filter(
            amount_paid__gt=0
        ).exists()

        if has_paid_before:
            return False, "You are not eligible for the free trial because you have previously paid for a plan."

        # 3. Has already used the free trial?
        has_used_trial = subscriptions_qs.filter(
            metadata__used_free_trial=True
        ).exists()

        if has_used_trial:
            return False, "You have already used your one-time 14-day free Pro trial."

        # 4. Has at least one saved card?
        has_card = PaymentCard.objects.filter(user=host.user).exists()
        if not has_card:
            return False, "Please add a payment card to your account before activating the free trial."

        return True, "You are eligible for the 14-day free Pro trial."

class PromoCodeService:

    @staticmethod
    def get_host_promo_codes(host, event_id=None, status=None, search=None):
        today = timezone.now().date()

        qs = (
            PromoCode.objects
            .select_related(
                "ticket",
                "ticket__event",
                "ticket__event__category",
            )
            .prefetch_related("ticket__event__media")
            .filter(ticket__event__host=host)
        )

        if event_id:
            qs = qs.filter(ticket__event_id=event_id)
        if status == "active":
            qs = qs.filter(valid_till__gte=today)
        elif status == "ended":
            qs = qs.filter(valid_till__lt=today)
        if search:
            qs = qs.filter(code__icontains=search)

        promo_codes_in_qs = list(qs.values_list("code", flat=True))
        usage_map = PromoCodeService._usage_map(host, promo_codes_in_qs)

        promo_list = list(qs)
        for promo in promo_list:
            stats = usage_map.get(promo.code, {})
            promo.usage_count    = stats.get("usage_count", 0)
            promo.revenue_impact = stats.get("revenue_impact", Decimal("0.00"))

        return promo_list

    @staticmethod
    def _usage_map(host, codes):
        """
        Revenue impact explained
        ────────────────────────
        When a promo code is applied at checkout, _apply_promo() calculates the
        discount and _create_order() stores:
          - Order.discount       = the actual money subtracted from the subtotal
          - Order.metadata       = {"promo_code": "<code>", ...}

        So for each code we query completed orders where metadata["promo_code"]
        matches, then:
          usage_count    = COUNT(order.id)         — how many times the code was used
          revenue_impact = SUM(order.discount)     — total money discounted via this code

        This is accurate because Order.discount is set per-order at the moment
        the promo is applied, so it captures the real discount even if the
        discount_percentage changes later.
        """
        rows = (
            Order.objects
            .filter(
                event__host=host,
                status="completed",
                metadata__promo_code__in=codes,
            )
            .values("metadata__promo_code")
            .annotate(
                usage_count=Count("id"),
                revenue_impact=Sum("discount"),
            )
        )
        return {
            row["metadata__promo_code"]: {
                "usage_count":    row["usage_count"],
                "revenue_impact": row["revenue_impact"] or Decimal("0.00"),
            }
            for row in rows
        }

    @staticmethod
    def create_promo_code(host, data):
        """
        Create the promo code for every ticket under the event in one go.
        Raises PromoCodeError if:
          - the event doesn't belong to this host
          - the event has no tickets
          - the code already exists on any ticket in that event
        """
        from events.models import Event

        # Verify event ownership
        try:
            event = Event.objects.get(id=data["event_id"], host=host)
        except Event.DoesNotExist:
            raise PromoCodeError(
                "Event not found or does not belong to you.", 404
            )

        tickets = list(Ticket.objects.filter(event=event))
        if not tickets:
            raise PromoCodeError(
                "This event has no tickets to attach a promo code to.", 400
            )

        # Prevent duplicate code on any ticket in this event
        if PromoCode.objects.filter(
            ticket__event=event, code=data["code"]
        ).exists():
            raise PromoCodeError(
                "A promo code with this code already exists for this event.", 400
            )

        # Bulk-create one PromoCode per ticket
        promos = PromoCode.objects.bulk_create([
            PromoCode(
                ticket=ticket,
                code=data["code"],
                discount_percentage=data["discount_percentage"],
                maximum_users=data["usage_limit"],
                valid_till=data["valid_until"],
            )
            for ticket in tickets
        ])

        return event, promos


class PromoCodeError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)


# ── Affiliates ─────────────────────────────────────────────────────────────────

class AffiliateService:

    @staticmethod
    def get_host_affiliates(host, event_id=None, search=None):
        """
        Returns (cards_dict, ranked_affiliate_list).

        Rank is determined by sales descending — the affiliate with the most
        sales gets rank 1. Ties share the same rank.
        """
        qs = (
            AffiliateLink.objects
            .select_related(
                "user",
                "user__attendee_profile",   # ← full_name lives here
                "event",
                "event__category",
            )
            .prefetch_related("event__media", "earnings")
            .filter(event__host=host)
            .annotate(
                total_earnings=Sum(
                    "earnings__earning",
                    filter=Q(earnings__status="succeeded"),
                )
            )
        )

        if event_id:
            qs = qs.filter(event_id=event_id)

        if search:
            # Search against Attendee.full_name and user.email
            qs = qs.filter(
                Q(user__attendee_profile__full_name__icontains=search) |
                Q(user__email__icontains=search)
            )

        cards = AffiliateService._cards(qs)

        # Materialise and rank by sales descending
        affiliate_list = list(qs.order_by("-sales"))
        AffiliateService._attach_ranks(affiliate_list)

        # Normalise None earnings to Decimal zero
        for link in affiliate_list:
            if link.total_earnings is None:
                link.total_earnings = Decimal("0.00")

        return cards, affiliate_list

    @staticmethod
    def _attach_ranks(affiliate_list):
        """
        Dense rank by sales descending.
        e.g. sales [10, 10, 7, 3] → ranks [1, 1, 2, 3]
        """
        rank = 1
        for i, link in enumerate(affiliate_list):
            if i == 0:
                link.rank = 1
            else:
                if link.sales < affiliate_list[i - 1].sales:
                    rank = i + 1
                link.rank = rank

    @staticmethod
    def _cards(qs):
        from django.utils import timezone

        now         = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ── total affiliates in the filtered scope ────────────────────────────
        total_affiliates = qs.count()

        # ── new this month: affiliate links created in the current calendar month
        # Uses the same filtered qs so event/search filters still apply.
        new_this_month = qs.filter(created_at__gte=month_start).count()

        # ── total tickets sold: sum of AffiliateLink.sales across filtered links
        # AffiliateLink.sales is incremented by your payment webhook each time
        # a ticket is purchased via that affiliate link.
        agg = qs.aggregate(
            tickets_sold=Sum("sales"),
            commission_paid=Sum(
                "earnings__earning",
                filter=Q(earnings__status="succeeded"),
            ),
        )

        return {
            "total_affiliates":      total_affiliates,
            "new_this_month":        new_this_month,
            "total_tickets_sold":    agg["tickets_sold"]    or 0,
            "total_commission_paid": agg["commission_paid"] or Decimal("0.00"),
        }


class CheckInService:

    # ── Overview cards ─────────────────────────────────────────────────────────

    @staticmethod
    def get_cards(host, event_id=None):
        """
        total_tickets  : all IssuedTickets for host's events
        total_checkins : CheckIn rows with status=checked_in
        issues         : CheckIn rows with status=duplicate or invalid
        All filterable by event.
        """
        tickets_qs = IssuedTicket.objects.filter(event__host=host)
        if event_id:
            tickets_qs = tickets_qs.filter(event_id=event_id)

        total_tickets = tickets_qs.count()

        checkins_qs = CheckIn.objects.filter(
            issued_ticket__event__host=host
        )
        if event_id:
            checkins_qs = checkins_qs.filter(issued_ticket__event_id=event_id)

        agg = checkins_qs.aggregate(
            total_checkins=Count("id", filter=Q(status="checked_in")),
            issues=Count("id", filter=Q(status__in=["duplicate", "invalid"])),
        )

        return {
            "total_tickets":  total_tickets,
            "total_checkins": agg["total_checkins"],
            "issues":         agg["issues"],
        }

    # ── Attendee list ──────────────────────────────────────────────────────────

    @staticmethod
    def get_attendees(host, event_id=None, ticket_type=None, status=None):
        """
        Returns IssuedTicket queryset for the host's events,
        with checkin prefetched so the serializer has no N+1 queries.

        status filter maps to CheckIn.status or 'pending' (no CheckIn row).
        """
        qs = (
            IssuedTicket.objects
            .select_related(
                "owner",
                "owner__attendee_profile",
                "order_ticket__ticket",
                "event",
                "event__category",
            )
            .prefetch_related("event__media", "checkin")
            .filter(event__host=host)
        )

        if event_id:
            qs = qs.filter(event_id=event_id)

        if ticket_type:
            qs = qs.filter(order_ticket__ticket_id=ticket_type)

        if status:
            if status == "pending":
                # No CheckIn row exists yet
                qs = qs.filter(checkin__isnull=True)
            else:
                qs = qs.filter(checkin__status=status)

        return qs.order_by("-created_at")

    # ── QR Scan ────────────────────────────────────────────────────────────────

    @staticmethod
    def process_scan(token: str, scanned_by=None) -> dict:
        """
        Verifies the signed token, checks the ticket, records the scan.

        Returns a result dict consumed directly by the view.
        All outcomes (valid, duplicate, invalid) are recorded in CheckIn
        for a full audit log.
        """

        # ── Step 1: verify token signature ────────────────────────────────────
        try:
            issued_ticket_id, token_owner_id = verify_checkin_token(token)
        except (signing.BadSignature, signing.SignatureExpired):
            CheckIn.objects.create(
                issued_ticket=None,
                scanned_token=token,
                status="invalid",
                scanned_by=scanned_by,
                notes="Token failed signature verification.",
            )
            return {
                "status":           "invalid",
                "message":          "Invalid or tampered QR code.",
                "issued_ticket_id": None,
                "full_name":        None,
                "ticket_type":      None,
                "event_name":       None,
                "checked_in_at":    None,
            }

        # ── Step 2: look up the ticket ────────────────────────────────────────
        try:
            ticket = (
                IssuedTicket.objects
                .select_related(
                    "owner__attendee_profile",
                    "order_ticket__ticket",
                    "event",
                )
                .get(id=issued_ticket_id)
            )
        except IssuedTicket.DoesNotExist:
            CheckIn.objects.create(
                issued_ticket=None,
                scanned_token=token,
                status="invalid",
                scanned_by=scanned_by,
                notes=f"IssuedTicket {issued_ticket_id} not found.",
            )
            return {
                "status":           "invalid",
                "message":          "Ticket not found.",
                "issued_ticket_id": None,
                "full_name":        None,
                "ticket_type":      None,
                "event_name":       None,
                "checked_in_at":    None,
            }

        # ── Step 3: verify the token belongs to the current owner ─────────────
        # If the ticket was transferred or resold, ticket.owner has changed.
        # The previous owner's token encodes their old owner_id — it won't
        # match the current owner so we reject it immediately.
        if ticket.owner_id != token_owner_id:
            CheckIn.objects.create(
                issued_ticket=ticket,
                scanned_token=token,
                status="invalid",
                scanned_by=scanned_by,
                notes=(
                    f"Owner mismatch: token encodes owner {token_owner_id} "
                    f"but current owner is {ticket.owner_id}. "
                    "Ticket may have been transferred."
                ),
            )
            return {
                "status":           "invalid",
                "message":          "This QR code is no longer valid. "
                                    "The ticket has been transferred to a new owner.",
                "issued_ticket_id": str(ticket.id),
                "full_name":        None,
                "ticket_type":      None,
                "event_name":       ticket.event.title,
                "checked_in_at":    None,
            }
    
        if ticket.status in ["cancelled", "used"]:
            CheckIn.objects.create(
                issued_ticket=ticket,
                scanned_token=token,
                status="invalid",
                scanned_by=scanned_by,
                notes=f"Attempted check-in with invalid ticket status: {ticket.status}",
            )
            return {
                "status":           "invalid",
                "message":          f"This ticket is {ticket.status} and cannot be used.",
                "issued_ticket_id": str(ticket.id),
                "full_name":        None,
                "ticket_type":      None,
                "event_name":       ticket.event.title,
                "checked_in_at":    None,
            }

        attendee = getattr(ticket.owner, "attendee_profile", None)
        full_name   = attendee.full_name if attendee else ticket.owner.email
        ticket_type = ticket.order_ticket.ticket.ticket_type
        event_name  = ticket.event.title

        # ── Step 4: check for existing check-in ──────────────────────────────
        # OneToOne guarantees only one CheckIn per ticket.
        # If one already exists, return early with a clear message.
        existing = getattr(ticket, "checkin", None)
        if existing:
            return {
                "status":           "already_checked_in",
                "message":          "This ticket has already been checked in.",
                "issued_ticket_id": str(ticket.id),
                "full_name":        full_name,
                "ticket_type":      ticket_type,
                "event_name":       event_name,
                "checked_in_at":    existing.checked_in_at,
            }

        # ── Step 5: first valid scan — check in ───────────────────────────────
        with transaction.atomic():
            checkin = CheckIn.objects.create(
                issued_ticket=ticket,
                scanned_token=token,
                status="checked_in",
                scanned_by=scanned_by,
            )
            # Mirror status on IssuedTicket
            IssuedTicket.objects.filter(id=ticket.id).update(status="used")

        return {
            "status":           "checked_in",
            "message":          "Check-in successful.",
            "issued_ticket_id": str(ticket.id),
            "full_name":        full_name,
            "ticket_type":      ticket_type,
            "event_name":       event_name,
            "checked_in_at":    checkin.checked_in_at,
        }



#DAHSBOARD SERVICES 

MONTH_NAMES = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
]


class DashboardService:

    # ── Endpoint 1: Cards + Chart ──────────────────────────────────────────────

    @staticmethod
    def get_cards(host):
        now        = timezone.now()
        week_ago   = now - timedelta(weeks=1)
        month_ago  = now - timedelta(days=30)
        last_month_start = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        last_month_end   = now.replace(day=1)

        base = Order.objects.filter(event__host=host, status="completed")

        # ── Total revenue ─────────────────────────────────────────────────────
        total_revenue = base.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")

        # Revenue change: this month vs last month (%)
        this_month_rev = (
            base.filter(created_at__gte=now.replace(day=1))
            .aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        )
        last_month_rev = (
            base.filter(
                created_at__gte=last_month_start,
                created_at__lt=last_month_end,
            ).aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        )
        revenue_change = (
            round(((float(this_month_rev) - float(last_month_rev))
                   / float(last_month_rev)) * 100, 2)
            if last_month_rev else 0.0
        )

        # ── Tickets sold ──────────────────────────────────────────────────────
        tickets_sold = (
            OrderTicket.objects
            .filter(order__event__host=host, order__status="completed")
            .aggregate(t=Sum("quantity"))["t"] or 0
        )
        tickets_sold_change = (
            OrderTicket.objects
            .filter(
                order__event__host=host,
                order__status="completed",
                order__created_at__gte=week_ago,
            )
            .aggregate(t=Sum("quantity"))["t"] or 0
        )

        # ── Active events ─────────────────────────────────────────────────────
        from events.models import Event
        active_events = Event.objects.filter(host=host, status="active").count()
        active_events_change = (
            Event.objects
            .filter(host=host, status="active", created_at__gte=week_ago)
            .count()
        )

        # ── Pending payouts ───────────────────────────────────────────────────
        from transactions.models import Withdrawal
        pending_payouts = (
            Withdrawal.objects
            .filter(user=host.user, status="pending")
            .aggregate(t=Sum("amount"))["t"] or Decimal("0")
        )
        pending_payouts_change = (
            Withdrawal.objects
            .filter(user=host.user, status="pending", created_at__gte=week_ago)
            .count()
        )

        return {
            "total_revenue":          total_revenue,
            "tickets_sold":           tickets_sold,
            "active_events":          active_events,
            "pending_payouts":        pending_payouts,
            "revenue_change":         revenue_change,
            "tickets_sold_change":    tickets_sold_change,
            "active_events_change":   active_events_change,
            "pending_payouts_change": pending_payouts_change,
        }

    @staticmethod
    def get_revenue_chart(host, year, month=None, week=None, chart_type="revenue"):
        """
        chart_type = "revenue" → sums total_amount (default)
        chart_type = "tickets" → sums ticket quantities
        """
        from django.db.models.functions import TruncMonth, TruncDay

        # ── Ticket chart ──────────────────────────────────────────────────────────
        if chart_type == "tickets":
            base = OrderTicket.objects.filter(
                order__event__host=host,
                order__status="completed",
            )
            if week:
                now = timezone.now()
                week_start = now - timedelta(days=now.weekday())
                week_end = week_start + timedelta(days=7)
                qs = (
                    base
                    .filter(order__created_at__gte=week_start, order__created_at__lt=week_end)
                    .annotate(period=TruncDay("order__created_at"))
                    .values("period")
                    .annotate(amount=Sum("quantity"))
                    .order_by("period")
                )
                return [
                    {
                        "label": row["period"].strftime("%a %d"),
                        "month": row["period"].month,
                        "amount": row["amount"] or 0,
                    }
                    for row in qs if row["period"]
                ]
            if month:
                qs = (
                    base
                    .filter(order__created_at__year=year, order__created_at__month=month)
                    .annotate(period=TruncDay("order__created_at"))
                    .values("period")
                    .annotate(amount=Sum("quantity"))
                    .order_by("period")
                )
                return [
                    {
                        "label": row["period"].strftime("%d %b"),
                        "month": row["period"].month,
                        "amount": row["amount"] or 0,
                    }
                    for row in qs if row["period"]
                ]
            qs = (
                base
                .filter(order__created_at__year=year)
                .annotate(period=TruncMonth("order__created_at"))
                .values("period")
                .annotate(amount=Sum("quantity"))
                .order_by("period")
            )
            monthly = {i: 0 for i in range(1, 13)}
            for row in qs:
                if row["period"]:
                    monthly[row["period"].month] = row["amount"] or 0
            return [
                {"label": MONTH_NAMES[m], "month": m, "amount": monthly[m]}
                for m in range(1, 13)
            ]

        # ── Revenue chart (default) ───────────────────────────────────────────────
        base = Order.objects.filter(event__host=host, status="completed",marketplace_listing__isnull=True)
        if week:
            # Current week — daily
            now = timezone.now()
            week_start = now - timedelta(days=now.weekday())
            week_end = week_start + timedelta(days=7)
            qs = (
                base
                .filter(created_at__gte=week_start, created_at__lt=week_end)
                .annotate(period=TruncDay("created_at"))
                .values("period")
                .annotate(amount=Sum("total_amount"))
                .order_by("period")
            )
            return [
                {
                    "label": row["period"].strftime("%a %d"),
                    "month": row["period"].month,
                    "amount": row["amount"] or Decimal("0"),
                }
                for row in qs if row["period"]
            ]
        if month:
            # Specific month — daily
            qs = (
                base
                .filter(created_at__year=year, created_at__month=month)
                .annotate(period=TruncDay("created_at"))
                .values("period")
                .annotate(amount=Sum("total_amount"))
                .order_by("period")
            )
            return [
                {
                    "label": row["period"].strftime("%d %b"),
                    "month": row["period"].month,
                    "amount": row["amount"] or Decimal("0"),
                }
                for row in qs if row["period"]
            ]
        # Default: full year — monthly buckets
        qs = (
            base
            .filter(created_at__year=year)
            .annotate(period=TruncMonth("created_at"))
            .values("period")
            .annotate(amount=Sum("total_amount"))
            .order_by("period")
        )
        # Build a full 12-month skeleton so months with no revenue show as 0
        monthly = {i: Decimal("0") for i in range(1, 13)}
        for row in qs:
            if row["period"]:
                monthly[row["period"].month] = row["amount"] or Decimal("0")
        return [
            {
                "label": MONTH_NAMES[m],
                "month": m,
                "amount": monthly[m],
            }
            for m in range(1, 13)
        ]

    # ── Endpoint 2: Activity + Notifications + Trending ───────────────────────

    @staticmethod
    def get_recent_activities(host, limit=10):
        return (
            HostActivity.objects
            .filter(host=host.user)
            .order_by("-created_at")[:limit]
        )

    @staticmethod
    def get_notifications(host, limit=20):
        return (
            HostNotification.objects
            .filter(host=host.user)
            .order_by("-created_at")[:limit]
        )

    @staticmethod
    def get_trending_tickets(host, limit=3):
        """
        Top N tickets by sold_count for this host's active events.
        Annotates revenue = sold_count × price.
        """
        return (
            Ticket.objects
            .select_related("event", "event__category")
            .prefetch_related("event__media")
            .filter(event__host=host, event__status="active")
            .annotate(
                revenue=Sum(
                    "orderticket__price",
                    filter=Q(
                        orderticket__order__status="completed"
                    ),
                )
            )
            .order_by("-sold_count")[:limit]
        )

    @staticmethod
    def mark_notifications_read(host):
        HostNotification.objects.filter(host=host.user, is_read=False).update(is_read=True)



#FINANCCIAL ANALYSIS 
class SalesCardService:

    @staticmethod
    def get_cards(host, date_range=None, event_id=None):
        now   = timezone.now()
        delta = {
            "day":   timedelta(days=1),
            "week":  timedelta(weeks=1),
            "month": timedelta(days=30),
        }
        d            = delta.get(date_range, timedelta(days=30))
        period_start = now - d
        prev_start   = period_start - d

        def _base(start=None, end=None, status="completed"):
            qs = Order.objects.filter(event__host=host, status=status)
            if event_id:
                qs = qs.filter(event_id=event_id)
            if start:
                qs = qs.filter(created_at__gte=start)
            if end:
                qs = qs.filter(created_at__lt=end)
            return qs

        def _tickets(start=None, end=None):
            qs = OrderTicket.objects.filter(
                order__event__host=host, order__status="completed"
            )
            if event_id:
                qs = qs.filter(order__event_id=event_id)
            if start:
                qs = qs.filter(order__created_at__gte=start)
            if end:
                qs = qs.filter(order__created_at__lt=end)
            return qs

        # ── Total revenue ─────────────────────────────────────────────────────
        total_revenue = (
            _base().aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        )
        curr_rev = (
            _base(period_start, now).aggregate(t=Sum("total_amount"))["t"]
            or Decimal("0")
        )
        prev_rev = (
            _base(prev_start, period_start).aggregate(t=Sum("total_amount"))["t"]
            or Decimal("0")
        )
        total_revenue_change = curr_rev - prev_rev

        # ── Tickets sold ──────────────────────────────────────────────────────
        tickets_sold = (
            _tickets().aggregate(t=Sum("quantity"))["t"] or 0
        )

        # ── Conversion rate ───────────────────────────────────────────────────
        cap_qs = Ticket.objects.filter(event__host=host)
        if event_id:
            cap_qs = cap_qs.filter(event_id=event_id)
        total_capacity  = cap_qs.aggregate(t=Sum("quantity"))["t"] or 0
        conversion_rate = (
            round((tickets_sold / total_capacity) * 100, 2)
            if total_capacity else 0.0
        )
        curr_sold = _tickets(period_start, now).aggregate(t=Sum("quantity"))["t"] or 0
        prev_sold = _tickets(prev_start, period_start).aggregate(t=Sum("quantity"))["t"] or 0
        conversion_change = _pct_change(curr_sold, prev_sold)

        # ── Average order value ───────────────────────────────────────────────
        curr_aov = (
            _base(period_start, now).aggregate(a=Avg("total_amount"))["a"]
            or Decimal("0")
        )
        prev_aov = (
            _base(prev_start, period_start).aggregate(a=Avg("total_amount"))["a"]
            or Decimal("0")
        )
        aov_change = _pct_change(curr_aov, prev_aov)

        # ── Page views ────────────────────────────────────────────────────────
        ev_qs = Event.objects.filter(host=host)
        if event_id:
            ev_qs = ev_qs.filter(id=event_id)
        page_views = ev_qs.aggregate(t=Sum("views_count"))["t"] or 0

        # ── Refunds ───────────────────────────────────────────────────────────
        refund_qs = Order.objects.filter(event__host=host, status="refunded")
        if event_id:
            refund_qs = refund_qs.filter(event_id=event_id)
        if date_range:
            refund_qs = _apply_day_range(refund_qs, date_range)
        refunds = refund_qs.count()

        # ── Repeat buyers ─────────────────────────────────────────────────────
        # Users who have placed more than 1 completed order with this host
        all_orders = Order.objects.filter(event__host=host, status="completed")
        if event_id:
            all_orders = all_orders.filter(event_id=event_id)
        repeat_buyers = (
            all_orders
            .values("user")
            .annotate(cnt=Count("id"))
            .filter(cnt__gt=1)
            .count()
        )

        return {
            "total_revenue":        total_revenue,
            "total_revenue_change": total_revenue_change,
            "tickets_sold":         tickets_sold,
            "conversion_rate":      conversion_rate,
            "conversion_change":    conversion_change,
            "average_order_value":  curr_aov,
            "aov_change":           aov_change,
            "page_views":           page_views,
            "refunds":              refunds,
            "repeat_buyers":        repeat_buyers,
        }


# ── Endpoint 2: Graphs ─────────────────────────────────────────────────────────

class SalesGraphService:

    @staticmethod
    def get_revenue_chart(host, filter_type=None, year=None, event_id=None):
        """
        filter_type = "week"  → daily for current week
        filter_type = "month" → daily for current calendar month
        filter_type = "year"  → monthly for given year (default current year)
        """
        now  = timezone.now()
        base = Order.objects.filter(event__host=host, status="completed")
        if event_id:
            base = base.filter(event_id=event_id)

        if filter_type == "week":
            week_start = now - timedelta(days=now.weekday())
            qs = (
                base
                .filter(created_at__gte=week_start)
                .annotate(period=TruncDay("created_at"))
                .values("period")
                .annotate(amount=Sum("total_amount"))
                .order_by("period")
            )
            return [
                {
                    "label":  r["period"].strftime("%a %d"),
                    "amount": r["amount"] or Decimal("0"),
                }
                for r in qs if r["period"]
            ]

        if filter_type == "month":
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            qs = (
                base
                .filter(created_at__gte=month_start)
                .annotate(period=TruncDay("created_at"))
                .values("period")
                .annotate(amount=Sum("total_amount"))
                .order_by("period")
            )
            return [
                {
                    "label":  r["period"].strftime("%d %b"),
                    "amount": r["amount"] or Decimal("0"),
                }
                for r in qs if r["period"]
            ]

        # Default: full year monthly buckets
        y = year or now.year
        qs = (
            base
            .filter(created_at__year=y)
            .annotate(period=TruncMonth("created_at"))
            .values("period")
            .annotate(amount=Sum("total_amount"))
            .order_by("period")
        )
        monthly = {i: Decimal("0") for i in range(1, 13)}
        for r in qs:
            if r["period"]:
                monthly[r["period"].month] = r["amount"] or Decimal("0")

        return [
            {"label": MONTH_NAMES[m], "amount": monthly[m]}
            for m in range(1, 13)
        ]

    @staticmethod
    def get_sales_breakdown(host, event_id=None):
        """
        Returns overall ticket type breakdown + breakdown by time-of-day period.
        Uses DB-level hour extraction so no Python looping over rows.
        """
        base = OrderTicket.objects.filter(
            order__event__host=host, order__status="completed"
        )
        if event_id:
            base = base.filter(order__event_id=event_id)

        # Overall by ticket type
        by_type = (
            base
            .values("ticket__ticket_type")
            .annotate(count=Sum("quantity"))
            .order_by("-count")
        )
        total = sum(r["count"] or 0 for r in by_type)

        overall = [
            {
                "ticket_type": r["ticket__ticket_type"],
                "count":       r["count"] or 0,
                "percentage":  round((r["count"] / total) * 100, 2) if total else 0.0,
            }
            for r in by_type
        ]

        # Time-of-day periods
        periods = [
            ("Morning (12am - 12pm)",  Q(order__created_at__hour__lt=12)),
            ("Afternoon (12pm - 6pm)", Q(order__created_at__hour__gte=12,
                                         order__created_at__hour__lt=18)),
            ("Evening (6pm - 12am)",   Q(order__created_at__hour__gte=18)),
        ]

        by_period = []
        for label, period_q in periods:
            period_qs    = base.filter(period_q)
            period_total = period_qs.aggregate(t=Sum("quantity"))["t"] or 0
            type_rows    = (
                period_qs
                .values("ticket__ticket_type")
                .annotate(count=Sum("quantity"))
                .order_by("-count")
            )
            by_period.append({
                "period_label": label,
                "total":        period_total,
                "by_ticket_type": [
                    {
                        "ticket_type": r["ticket__ticket_type"],
                        "count":       r["count"] or 0,
                        "percentage":  round((r["count"] / period_total) * 100, 2)
                                       if period_total else 0.0,
                    }
                    for r in type_rows
                ],
            })

        return {"overall": overall, "by_period": by_period}

    @staticmethod
    def get_week_analysis(host, event_id=None):
        now         = timezone.now()
        week_start  = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        prev_start  = week_start - timedelta(weeks=1)
        prev_end    = week_start

        base = Order.objects.filter(event__host=host, status="completed")
        if event_id:
            base = base.filter(event_id=event_id)

        def _count(qs):
            return (
                OrderTicket.objects
                .filter(order__in=qs)
                .aggregate(t=Sum("quantity"))["t"] or 0
            )

        this_week_count = _count(base.filter(created_at__gte=week_start))
        last_week_count = _count(
            base.filter(created_at__gte=prev_start, created_at__lt=prev_end)
        )
        change = _pct_change(this_week_count, last_week_count)

        week_end = week_start + timedelta(days=7)
        label = (
            f"Sales from {week_start.strftime('%-d')}–"
            f"{(week_end - timedelta(days=1)).strftime('%-d %b, %Y')}"
        )

        days = []
        for i in range(7):
            day_start = week_start + timedelta(days=i)
            day_end   = day_start + timedelta(days=1)

            day_orders = base.filter(created_at__gte=day_start, created_at__lt=day_end)

            morning = (
                OrderTicket.objects
                .filter(order__in=day_orders, order__created_at__hour__lt=12)
                .aggregate(t=Sum("quantity"))["t"] or 0
            )
            afternoon = (
                OrderTicket.objects
                .filter(
                    order__in=day_orders,
                    order__created_at__hour__gte=12,
                    order__created_at__hour__lt=18,
                )
                .aggregate(t=Sum("quantity"))["t"] or 0
            )
            evening = (
                OrderTicket.objects
                .filter(order__in=day_orders, order__created_at__hour__gte=18)
                .aggregate(t=Sum("quantity"))["t"] or 0
            )
            days.append({
                "day":       day_start.strftime("%a"),
                "date":      day_start.date(),
                "morning":   morning,
                "afternoon": afternoon,
                "evening":   evening,
                "total":     morning + afternoon + evening,
            })

        return {"change_vs_last_week": change, "label": label, "days": days}

    @staticmethod
    def get_geo_breakdown(host, event_id=None):
        base = (
            Order.objects
            .filter(event__host=host, status="completed")
            .filter(event__event_location__isnull=False)  # JOIN — no subquery needed
        )

        if event_id:
            base = base.filter(event_id=event_id)

        rows = (
            base
            .values(
                city=F("event__event_location__city"),
                state=F("event__event_location__state"),
            )
            .annotate(
                tickets=Sum("tickets__quantity"),
                revenue=Sum("total_amount"),
            )
            .order_by("-tickets")
        )

        ev_qs = Event.objects.filter(host=host).select_related("event_location")
        if event_id:
            ev_qs = ev_qs.filter(id=event_id)

        click_map = {}
        for ev in ev_qs:
            loc = getattr(ev, "event_location", None)
            if loc:
                key = (loc.city, loc.state)
                click_map[key] = click_map.get(key, 0) + ev.views_count

        locations = [
            {
                "city":    r["city"],
                "state":   r["state"],
                "tickets": r["tickets"] or 0,
                "revenue": r["revenue"] or Decimal("0"),
                "clicks":  click_map.get((r["city"], r["state"]), 0),
            }
            for r in rows
            if r["city"]
        ]

        best = max(locations, key=lambda x: x["tickets"], default=None)
        best_location = (
            {
                "label":   f"{best['city']}, {best['state']}",
                "tickets": best["tickets"],
                "revenue": best["revenue"],
                "clicks":  best["clicks"],
            }
            if best else None
        )

        return {"locations": locations, "best_location": best_location}

    @staticmethod
    def get_all_graphs(host, filter_type, year, event_id, plan_slug):
        """
        Combined method for SalesGraphsView.
        Handles plan-based feature gating — locked features return None
        so no unnecessary DB queries run for plans that can't access them.
        """
        from host.plan_limits import has_feature

        # sales_breakdown is free for all plans — always compute
        breakdown = SalesGraphService.get_sales_breakdown(host, event_id=event_id)

        # revenue_chart — enterprise only
        revenue = (
            SalesGraphService.get_revenue_chart(
                host, filter_type=filter_type, year=year, event_id=event_id
            )
            if has_feature(plan_slug, "revenue_chart") else None
        )

        # week_analysis — enterprise only
        week = (
            SalesGraphService.get_week_analysis(host, event_id=event_id)
            if has_feature(plan_slug, "week_analysis") else None
        )

        # geo_breakdown — enterprise only
        geo = (
            SalesGraphService.get_geo_breakdown(host, event_id=event_id)
            if has_feature(plan_slug, "geo_breakdown") else None
        )

        return breakdown, revenue, week, geo

# ── Endpoint 3: Transactions ───────────────────────────────────────────────────

class TransactionService:

    @staticmethod
    def get_transactions(host, ticket_type_id=None, date_range=None,
                         search=None, event_id=None,start_date=None,end_date=None):
        qs = (
            Order.objects
            .select_related(
                "user",
                "user__attendee_profile",
                "event",
                "event__category",
            )
            .prefetch_related("event__media", "tickets")
            .filter(event__host=host,status="completed")
        )
        if start_date or end_date:

            if start_date and end_date:
                qs = qs.filter(
                    created_at__date__gte=start_date,
                    created_at__date__lte=end_date
                )

            elif start_date:
                qs = qs.filter(
                    created_at__date__gte=start_date
                )

            elif end_date:
                qs = qs.filter(
                    created_at__date__lte=end_date
                )

        if event_id:
            qs = qs.filter(event_id=event_id)

        if ticket_type_id:
            qs = qs.filter(tickets__ticket_id=ticket_type_id)

        if date_range:
            qs = _apply_day_range(qs, date_range)

        if search:
            qs = qs.filter(
                Q(user__attendee_profile__full_name__icontains=search) |
                Q(user__email__icontains=search)                       |
                Q(event__title__icontains=search)
            )

        return qs.distinct().order_by("-created_at")



class DownloadEventAttendeeService:

    @staticmethod
    def get_attendees(host, event_id, search=None):
        qs = (
            IssuedTicket.objects
            .select_related(
                "owner",
                "owner__attendee_profile",
                "order",
                "order_ticket__ticket",
            )
            .prefetch_related("checkin")
            .filter(event_id=event_id, event__host=host)
        )

        if search:
            qs = qs.filter(
                Q(owner__attendee_profile__full_name__icontains=search) |
                Q(owner__email__icontains=search)
            )

        return qs.order_by("owner__attendee_profile__full_name")