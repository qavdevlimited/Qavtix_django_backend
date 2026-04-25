# host/mixins.py

from host.plan_limits import (
    get_host_plan_slug,
    has_feature,
    get_limit,
    which_plan_unlocks,
)
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

class PlanFeatureMixin:
    """
    Universal plan enforcement mixin — three cases:

    Case 1 — Hard block entire view:
        class CheckInOverviewView(PlanFeatureMixin, generics.ListAPIView):
            required_feature = "qr_checkin"

    Case 2 — Soft lock per section (analytics graphs):
        class SalesGraphsView(PlanFeatureMixin, APIView):
            def get(self, request):
                return api_response(data={
                    "revenue_chart": self.get_locked_response("revenue_chart", revenue_data),
                    "geo_breakdown": self.get_locked_response("geo_breakdown", geo_data),
                    "week_analysis": self.get_locked_response("week_analysis", week_data),
                })

    Case 3 — Count/create-time limits (declare flags on view):
        class EventCreateView(PlanFeatureMixin, generics.CreateAPIView):
            check_active_events    = True
            check_ticket_types     = True
            check_promo_codes      = True
            check_affiliate        = True
            check_team_permissions = True
    """

    # Case 1 — hard block
    required_feature = None
    upgrade_message  = None

    # Case 3 — create-time flags
    check_active_events    = False
    check_ticket_types     = False
    check_promo_codes      = False
    check_affiliate        = False
    check_team_permissions = False
    check_promo_code_limit = False
    check_ticket_limit = False

    # ── Core helpers ──────────────────────────────────────────────────────────

    def get_host_plan(self) -> str:
        """
        Returns the current plan slug for the requesting host.
        Cached after first call — no repeated DB hits per request.
        """
        if hasattr(self, "_cached_plan_slug"):
            return self._cached_plan_slug

        host = getattr(self.request.user, "host_profile", None)
        if not host:
            self._cached_plan_slug = "free"
            return "free"

        self._cached_plan_slug = get_host_plan_slug(host)
        return self._cached_plan_slug

    def host_has_feature(self, feature: str) -> bool:
        """Returns True if the host's current plan includes the feature."""
        return has_feature(self.get_host_plan(), feature)

    def host_get_limit(self, feature: str):
        """Returns the numeric limit for a feature on the host's current plan."""
        return get_limit(self.get_host_plan(), feature)

    def get_export_limit(self):
        """
        Returns the attendee export row limit for the host's plan.
        Returns None for unlimited (enterprise).
        """
        return self.host_get_limit("attendee_export_limit")

    # ── dispatch — completely untouched ──────────────────────────────────────
    # We do NOT override dispatch at all.
    # All blocking happens in initial() which DRF calls after setting up
    # the renderer — so PermissionDenied raised here goes through
    # handle_exception() → finalize_response() correctly.

    # ── initial — runs after DRF wraps request and sets up renderer ───────────

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)

        # Case 1 — hard block the entire view
        if self.required_feature:
            plan_slug = self.get_host_plan()
            if not has_feature(plan_slug, self.required_feature):
                upgrade_to = which_plan_unlocks(self.required_feature)
                raise PermissionDenied(detail={
                    "message": self.upgrade_message or (
                        f"This feature is not available on your current plan. "
                        f"Upgrade to {upgrade_to.capitalize()} to unlock it."
                    ),
                    "feature":    self.required_feature,
                    "your_plan":  plan_slug,
                    "upgrade_to": upgrade_to,
                })

        # Case 3 — create-time limits (POST only)
        if request.method == "POST" and any([
            self.check_active_events,
            self.check_ticket_types,
            self.check_promo_codes,
            self.check_affiliate,
            self.check_team_permissions,
            self.check_promo_code_limit, 
            self.check_ticket_limit,
        ]):
            self._run_create_limits(request)

    # ── _run_create_limits ────────────────────────────────────────────────────

    def _run_create_limits(self, request):
        """
        Runs all declared create-time checks.
        Raises PermissionDenied if any check fails.
        DRF catches PermissionDenied and routes through finalize_response()
        so accepted_renderer is always set correctly.
        """
        host      = getattr(request.user, "host_profile", None)
        plan_slug = self.get_host_plan()
        data      = request.data

        # 1 — Active event limit
        if self.check_active_events and host:
            from events.models import Event
            active_count = Event.objects.filter(host=host, status="active").count()
            self._raise_if_limited("max_active_events", active_count, plan_slug)

        # 2 — Ticket type limit
        if self.check_ticket_types:
            tickets = data.get("tickets", [])
            self._raise_if_limited("max_ticket_types", len(tickets), plan_slug)

        # 3 — Promo codes
        if self.check_promo_codes and not has_feature(plan_slug, "promo_codes"):
            tickets = data.get("tickets", [])
            for ticket in tickets:
                if ticket.get("promo_codes"):
                    raise PermissionDenied(detail={
                        "message":    "Promo codes are not available on your plan. Upgrade to Pro.",
                        "feature":    "promo_codes",
                        "your_plan":  plan_slug,
                        "upgrade_to": which_plan_unlocks("promo_codes"),
                    })

        # 4 — Affiliate setting
        if self.check_affiliate and not has_feature(plan_slug, "affiliate"):
            if data.get("affiliate_enabled"):
                raise PermissionDenied(detail={
                    "message":    "Affiliate program is not available on your plan. Upgrade to Pro.",
                    "feature":    "affiliate",
                    "your_plan":  plan_slug,
                    "upgrade_to": which_plan_unlocks("affiliate"),
                })

        # 5 — Custom sender name
        if self.check_team_permissions and not has_feature(plan_slug, "advanced_event_setup"):
            if data.get("customize_sender_name"):
                raise PermissionDenied(detail={
                    "message":    "Custom sender name is not available on your plan. Upgrade to Pro.",
                    "feature":    "advanced_event_setup",
                    "your_plan":  plan_slug,
                    "upgrade_to": which_plan_unlocks("advanced_event_setup"),
                })

        # 6 — Team permissions
        if self.check_team_permissions:
            permissions_data = data.get("permissions", [])
            if permissions_data:
                if not has_feature(plan_slug, "advanced_event_setup"):
                    raise PermissionDenied(detail={
                        "message":    "Team permissions are not available on your plan. Upgrade to Pro.",
                        "feature":    "team_permissions",
                        "your_plan":  plan_slug,
                        "upgrade_to": which_plan_unlocks("team_permissions"),
                    })
                self._raise_if_limited("team_permissions", len(permissions_data), plan_slug)

        # 7 — Promo code count limit (standalone create, not inside event)
        if self.check_promo_code_limit:
            from events.models import PromoCode
            existing_count = (
                PromoCode.objects
                .filter(ticket__event__host=host)
                .values("code")
                .distinct()
                .count()
            )
            self._raise_if_limited("promo_code_limit", existing_count, plan_slug)

        # 8 — Total ticket quantity limit per event
        if self.check_ticket_limit:
            tickets = data.get("tickets", [])
            total_quantity = sum(
                int(t.get("quantity", 0)) for t in tickets
            )
            self._raise_if_limited("event_ticket_limit", total_quantity, plan_slug)

        # 9 — QRCode check-in
        if self.check_team_permissions and not has_feature(plan_slug, "advanced_event_setup"):
            if data.get("qr_enabled"):
                raise PermissionDenied(detail={
                    "message":    "QR code check-in is not available on your plan. Upgrade to Pro.",
                    "feature":    "advanced_event_setup",
                    "your_plan":  plan_slug,
                    "upgrade_to": which_plan_unlocks("advanced_event_setup"),
                })

    # ── _raise_if_limited ─────────────────────────────────────────────────────

    def _raise_if_limited(self, feature: str, current_count: int, plan_slug: str):
        """
        Checks numeric limit for a feature.
        Raises PermissionDenied if current_count exceeds the limit.
        Does nothing if limit is None (unlimited) or count is within limit.
        """
        limit = get_limit(plan_slug, feature)

        # None = unlimited — always pass
        if limit is None:
            return

        if current_count > limit:
            messages = {
                "max_active_events":     f"You have reached the limit of {limit} active event(s) on your plan.",
                "max_ticket_types":      f"Your plan only allows {limit} ticket type(s) per event.",
                "promo_code_limit":      f"You have reached the limit of {limit} promo code(s) on your plan.",
                "team_permissions":      f"Your plan allows a maximum of {limit} team member(s).",
                "email_campaign_limit":  f"You have reached your monthly email campaign limit of {limit}.",
                "attendee_export_limit": f"Your plan allows exporting up to {limit} attendees.",
                "event_ticket_limit": f"Your plan allows a maximum of {limit} total tickets per event.",
            }
            raise PermissionDenied(detail={
                "message":       messages.get(
                    feature,
                    "You have reached the limit for this feature on your current plan.",
                ),
                "feature":       feature,
                "limit":         limit,
                "current_count": current_count,
                "your_plan":     plan_slug,
                "upgrade_to":    which_plan_unlocks(feature),
            })

    # ── Case 2: Soft lock ─────────────────────────────────────────────────────

    def get_locked_response(self, feature: str, data=None) -> dict:
        """
        Returns a dict with locked flag, data, and upgrade_to.
        Use this for analytics sections where you show a locked card
        instead of blocking the whole view.

        Usage:
            "geo_breakdown": self.get_locked_response("geo_breakdown", geo_data)

        Returns when unlocked:
            { "locked": False, "data": <data> }

        Returns when locked:
            { "locked": True, "data": None, "upgrade_to": "enterprise" }
        """
        plan_slug = self.get_host_plan()
        if has_feature(plan_slug, feature):
            return {"locked": False, "data": data}
        return {
            "locked":     True,
            "data":       None,
            "upgrade_to": which_plan_unlocks(feature),
        }

    # ── Case 3: Manual count limit (call directly in a view if needed) ────────

    def check_count_limit(self, feature: str, current_count: int):
        """
        Manual count check — call directly in a view handler if needed.
        Raises PermissionDenied if limit exceeded.

        Usage:
            active = Event.objects.filter(host=host, status="active").count()
            self.check_count_limit("max_active_events", active)
        """
        self._raise_if_limited(feature, current_count, self.get_host_plan())





class IsVerifiedHost(BasePermission):
    message = "You must be a verified host to perform this action."

    def has_permission(self, request, view):
        user = request.user
        return (
            user.is_authenticated and
            hasattr(user, "host_profile") and
            user.host_profile.verified
        )