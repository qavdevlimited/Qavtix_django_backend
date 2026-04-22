import logging
from django.db.models import Q
from administrator.rolecontrol import RoleControlService

logger = logging.getLogger(__name__)


class AdminWithdrawalListService:
    """
    Paginated withdrawal history for admin.
    Filterable by status, date range, amount range.
    Role-based access control applied.
    """

    @staticmethod
    def get_withdrawals(
        user=None,   
        status=None,
        date_from=None,
        date_to=None,
        min_amount=None,
        max_amount=None,
        search=None,
    ):
        from transactions.models import Withdrawal

        qs = (
            Withdrawal.objects
            .select_related(
                "user",
                "user__attendee_profile",
                "payout_account",
            )
            .order_by("-created_at")
        )

        # ── RBAC FILTER (IMPORTANT) ────────────────────────────────
        if user:
            qs = RoleControlService.filter_by_admin(user, qs, "withdrawal")

        # ── Status filter ───────────────────────────────────────────
        if status:
            qs = qs.filter(status=status)

        # ── Date range ──────────────────────────────────────────────
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        # ── Amount range ────────────────────────────────────────────
        if min_amount is not None:
            qs = qs.filter(amount__gte=min_amount)
        if max_amount is not None:
            qs = qs.filter(amount__lte=max_amount)

        # ── Search ──────────────────────────────────────────────────
        if search:
            qs = qs.filter(
                Q(user__attendee_profile__full_name__icontains=search) |
                Q(user__email__icontains=search) |
                Q(payout_account__account_number__icontains=search)
            )

        return qs