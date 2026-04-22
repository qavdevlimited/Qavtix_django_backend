# administrator/service/financial_service.py

import logging
from decimal import Decimal
from django.db.models import Sum, Count, Q, F, OuterRef, Subquery, DecimalField
from django.utils import timezone
from datetime import timedelta
from administrator.models import AutoPayout
from marketplace.models import MarketListing
from administrator.rolecontrol import RoleControlService
logger = logging.getLogger(__name__)


def _get_since(date_range):
    now = timezone.now()
    if not date_range:
        return None, None
    if date_range == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), now
    elif date_range == "week":
        return now - timedelta(weeks=1), now
    elif date_range == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
    else:  # month default    
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0), now


# ─────────────────────────────────────────────────────────────────────────────
# Financial Cards
# ─────────────────────────────────────────────────────────────────────────────

class AdminFinancialCardService:

    @staticmethod
    def get_cards(date_range="month", event_id=None, user=None):
        from transactions.models import Order, Withdrawal
        from attendee.models import AffliateEarnings
        from payments.models import Payment
        

        since, until = _get_since(date_range)

       
        order_qs = Order.objects.filter(
            status="completed",
            created_at__gte=since,
            created_at__lt=until,
        )

        if user:
            order_qs = RoleControlService.filter_by_admin(user, order_qs, "order")

        if event_id:
            order_qs = order_qs.filter(event_id=event_id)

        total_gmv = order_qs.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        platform_fees = order_qs.aggregate(t=Sum("fees"))["t"] or Decimal("0")

      
        earnings_qs = AffliateEarnings.objects.all()

        if user:
            earnings_qs = RoleControlService.filter_by_admin(
                user,
                earnings_qs,
                "affliateearnings"
            )

        total_earned = (
            earnings_qs
            .filter(earning_type="affiliate")
            .aggregate(t=Sum("earning"))["t"] or Decimal("0")
        )

        total_paid_affiliate = (
            earnings_qs
            .filter(earning_type="affiliate", status="paid")
            .aggregate(t=Sum("earning"))["t"] or Decimal("0")
        )

        affiliate_balance = total_earned - total_paid_affiliate

        withdrawal_qs = Withdrawal.objects.filter(status="pending")

        if user:
            withdrawal_qs = RoleControlService.filter_by_admin(user, withdrawal_qs, "withdrawal")

        pending_payouts = withdrawal_qs.aggregate(t=Sum("amount"))["t"] or Decimal("0")

        return {
            "total_gmv": total_gmv,
            "platform_fees": platform_fees,
            "affiliate_balance": affiliate_balance,
            "pending_payouts": pending_payouts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Payout Requests — Pending
# ─────────────────────────────────────────────────────────────────────────────

class AdminPayoutRequestService:

    @staticmethod
    def get_pending(
        user=None,
        date_from=None,
        date_to=None,
        min_amount=None,
        max_amount=None,
        seller_id=None,
        search=None,
    ):
        from transactions.models import Withdrawal

        qs = (
            Withdrawal.objects
            .select_related(
                "user",
                "user__attendee_profile",
                "user__host_profile",
                "user__host_profile__auto_payout",
                "payout_account",
            )
            .filter(status="pending")
        )

       
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "withdrawal")

        return AdminPayoutRequestService._apply_filters(
            qs, date_from, date_to, min_amount, max_amount, seller_id, search
        )

    @staticmethod
    def get_approved(
        user=None,
        date_from=None,
        date_to=None,
        min_amount=None,
        max_amount=None,
        seller_id=None,
        search=None,
    ):
        from transactions.models import Withdrawal

        qs = (
            Withdrawal.objects
            .select_related(
                "user",
                "user__attendee_profile",
                "user__host_profile",
                "payout_account",
            )
            .filter(status__in=["approved", "paid"])
        )

       
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "withdrawal")

        return AdminPayoutRequestService._apply_filters(
            qs, date_from, date_to, min_amount, max_amount, seller_id, search
        )

    @staticmethod
    def _apply_filters(qs, date_from, date_to, min_amount, max_amount, seller_id, search):
        from django.db.models import Q

        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        if min_amount is not None:
            qs = qs.filter(amount__gte=min_amount)
        if max_amount is not None:
            qs = qs.filter(amount__lte=max_amount)
        if seller_id:
            qs = qs.filter(user_id=seller_id)

        if search:
            qs = qs.filter(
                Q(user__attendee_profile__full_name__icontains=search) |
                Q(user__host_profile__full_name__icontains=search) |
                Q(user__email__icontains=search)
            )

        return qs.order_by("-created_at")

    @staticmethod
    def get_seller_info(withdrawal):
        """Returns name, email, profile_picture for host or attendee."""
        user     = withdrawal.user
        host     = getattr(user, "host_profile", None)
        attendee = getattr(user, "attendee_profile", None)

        if host:
            auto_payout = getattr(host, "auto_payout", None)
            return {
                "host_id"  :            host.id,
                "name":            host.full_name,
                "email":           user.email,
                "profile_picture": host.profile_picture,
                "type":            "host",
                "business_name":   host.business_name,
                "auto_payout": auto_payout.is_enabled if auto_payout else False,
                "role"  :    "host"
            }
        if attendee:
            return {
                "attendee_id" :             attendee.id,
                "name":            attendee.full_name or user.email,
                "email":           user.email,
                "profile_picture": attendee.profile_picture,
                "type":            "attendee",
                "business_name":   None,
                "auto_payout": True,
                "role" :  "attendee"
            }
        return {
            "name":            user.email,
            "email":           user.email,
            "profile_picture": None,
            "type":            "unknown",
            "business_name":   None,
            "auto_payout"  : False
        }


# ─────────────────────────────────────────────────────────────────────────────
# Marketplace Listings
# ─────────────────────────────────────────────────────────────────────────────

class AdminMarketplaceListingService:

    @staticmethod
    def get_listings(
        user=None,
        status=None,
        seller_id=None,
        min_amount=None,
        max_amount=None,
        date_from=None,
        date_to=None,
        search=None,
    ):
        from marketplace.models import MarketListing
        from django.db.models import Q
        from administrator.rolecontrol import RoleControlService

        qs = (
            MarketListing.objects
            .select_related(
                "seller",
                "seller__attendee_profile",
                "seller__host_profile",
                "ticket",
                "ticket__event",
                "ticket__event__category",
            )
            .prefetch_related("ticket__event__media")
        )

        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "marketlisting")

        if status:
            qs = qs.filter(status__iexact=status)

        if seller_id:
            qs = qs.filter(seller_id=seller_id)

        if min_amount is not None:
            qs = qs.filter(price__gte=min_amount)

        if max_amount is not None:
            qs = qs.filter(price__lte=max_amount)

        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        if search:
            qs = qs.filter(
                Q(seller__attendee_profile__full_name__icontains=search) |
                Q(seller__host_profile__full_name__icontains=search) |
                Q(ticket__event__title__icontains=search)
            )

        return qs.order_by("-created_at")




class AdminFinancialResaleCardService:

    @staticmethod
    def get_cards(user=None, date_range=None, event_id=None):
        from marketplace.models import MarketListing
        from transactions.models import Order, Withdrawal

        since, until = _get_since(date_range)
        print(since,until)

        listing_qs = MarketListing.objects.all()
        order_qs = Order.objects.filter(
            status="completed",
            marketplace_listing__isnull=False,
        )

        if since and until:
            listing_qs = listing_qs.filter(created_at__gte=since, created_at__lt=until)
            order_qs = order_qs.filter(created_at__gte=since, created_at__lt=until)


        if user:
            listing_qs = RoleControlService.filter_by_admin(user, listing_qs, "marketlisting")

        

        if event_id:
            order_qs = order_qs.filter(event_id=event_id)

        total_gmv = order_qs.aggregate(t=Sum("total_amount"))["t"] or Decimal("0")
        platform_fees = order_qs.aggregate(t=Sum("fees"))["t"] or Decimal("0")

        total_resale_revenue = total_gmv + platform_fees

        total_listings = listing_qs.count()

        active_listings = listing_qs.filter(status="active").count()

        pending_payouts = Withdrawal.objects.filter(
            status="pending"
        ).aggregate(t=Sum("amount"))["t"] or Decimal("0")

        return {
            "total_resale_revenue": total_resale_revenue,
            "net_profit": total_gmv,
            "tickets_resold": total_listings,
            "active_listings": active_listings,
        }
# ─────────────────────────────────────────────────────────────────────────────
# Featured Event Payments
# ─────────────────────────────────────────────────────────────────────────────

class AdminFeaturedPaymentService:

    @staticmethod
    def get_featured_payments(
        user=None,
        plan_slug=None,
        status=None,
        min_amount=None,
        max_amount=None,
        date_from=None,
        date_to=None,
        search=None,
    ):
        from transactions.models import FeaturedEvent
        from django.db.models import Q

        qs = (
            FeaturedEvent.objects
            .select_related(
                "user",
                "user__host_profile",
                "event",
                "event__category",
            )
            .prefetch_related("event__media")
        )

        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "featuredevent")

        if plan_slug:
            qs = qs.filter(metadata__plan_slug=plan_slug)

        if status:
            qs = qs.filter(status__iexact=status)

        if min_amount is not None:
            qs = qs.filter(payment_amount__gte=min_amount)

        if max_amount is not None:
            qs = qs.filter(payment_amount__lte=max_amount)

        if date_from:
            qs = qs.filter(start_date__date__gte=date_from)

        if date_to:
            qs = qs.filter(start_date__date__lte=date_to)

        if search:
            qs = qs.filter(
                Q(user__host_profile__full_name__icontains=search) |
                Q(user__host_profile__business_name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(event__title__icontains=search)
            )

        return qs.order_by("-start_date")

# ─────────────────────────────────────────────────────────────────────────────
# Subscription Plan Payments
# ─────────────────────────────────────────────────────────────────────────────
class AdminSubscriptionPaymentService:

    @staticmethod
    def get_subscriptions(
        user=None,
        plan_slug=None,
        status=None,
        billing_cycle=None,
        min_amount=None,
        max_amount=None,
        date_from=None,
        date_to=None,
        search=None,
    ):
        from host.models import HostSubscription
        from django.db.models import Q

        qs = (
            HostSubscription.objects
            .select_related(
                "host",
                "host__user",
                "plan",
            )
            .exclude(plan_slug="free")
        )

        # RBAC FILTER
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "hoststrictsubscription")

        if plan_slug:
            qs = qs.filter(plan_slug=plan_slug)

        if status:
            qs = qs.filter(status__iexact=status)

        if billing_cycle:
            qs = qs.filter(billing_cycle=billing_cycle)

        if min_amount is not None:
            qs = qs.filter(amount_paid__gte=min_amount)

        if max_amount is not None:
            qs = qs.filter(amount_paid__lte=max_amount)

        if date_from:
            qs = qs.filter(started_at__date__gte=date_from)

        if date_to:
            qs = qs.filter(started_at__date__lte=date_to)

        if search:
            qs = qs.filter(
                Q(host__full_name__icontains=search) |
                Q(host__business_name__icontains=search) |
                Q(host__user__email__icontains=search)
            )

        return qs.order_by("-started_at")