# administrator/audit.py
# Wire this mixin into any admin view to auto-log every POST/PATCH/DELETE

import logging
from django.utils import timezone
from django.utils.dateparse import parse_datetime
logger = logging.getLogger(__name__)


def _get_client_ip(request):
    """
    Extracts the real client IP.
    Handles Vercel / proxy setups by checking X-Forwarded-For first.
    Takes the LAST trusted IP in the chain (rightmost non-internal),
    falling back to REMOTE_ADDR.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        # X-Forwarded-For: client, proxy1, proxy2
        # The leftmost is the original client — use it
        ip = xff.split(",")[0].strip()
        if ip:
            return ip

    # Direct connection — no proxy
    return request.META.get("REMOTE_ADDR", "")


class AuditLogMixin:
    """
    Add to any admin APIView or generics view to auto-log state-changing requests.

    Usage:
        class AdminUserSuspendView(AuditLogMixin, APIView):
            audit_action      = "user_suspend"
            audit_target_type = "user"

    For dynamic action/target (e.g. toggle suspend/unsuspend),
    call self.log_action() manually inside the view method instead.

    The mixin hooks into dispatch() — logs AFTER the response is built
    so it only records successful actions (2xx responses).
    """

    # Override these on the view class for simple cases
    audit_action      = "other"
    audit_target_type = ""

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)

        # Only log state-changing methods with successful responses
        if (
            request.method in ("POST", "PATCH", "PUT", "DELETE")
            and hasattr(response, "status_code")
            and 200 <= response.status_code < 300
            and request.user
            and request.user.is_authenticated
        ):
            try:
                self._auto_log(request, *args, **kwargs)
            except Exception as e:
                # Never let audit logging break the response
                logger.error(f"AuditLogMixin: failed to write log — {e}")

        return response

    def _auto_log(self, request, *args, **kwargs):
        """Default auto-log — uses class-level audit_action and audit_target_type."""
        target_id    = kwargs.get("user_id") or kwargs.get("host_id") or kwargs.get("event_id") or ""
        target_label = getattr(self, "_audit_target_label", "")

        AdminAuditLogService.log(
            request      = request,
            action       = self.audit_action,
            target_type  = self.audit_target_type,
            target_id    = str(target_id),
            target_label = target_label,
            details      = getattr(self, "_audit_details", ""),
        )

    def log_action(
        self,
        request,
        action,
        target_type="",
        target_id="",
        target_label="",
        details="",
    ):
        """
        Call manually from inside a view method for dynamic logging.
        Use when the action depends on runtime state (e.g. toggle suspend/unsuspend).

        Example:
            self.log_action(
                request,
                action       = "user_suspend" if was_active else "user_unsuspend",
                target_type  = "user",
                target_id    = str(user.id),
                target_label = user.email,
                details      = f"Suspended by {request.user.email}",
            )
        """
        AdminAuditLogService.log(
            request      = request,
            action       = action,
            target_type  = target_type,
            target_id    = str(target_id),
            target_label = target_label,
            details      = details,
        )


class AdminAuditLogService:
    """Writes audit log entries."""

    @staticmethod
    def log(request, action, target_type="", target_id="", target_label="", details=""):
        from administrator.models import AdminAuditLog

        try:
            AdminAuditLog.objects.create(
                admin        = request.user if request.user.is_authenticated else None,
                admin_email  = request.user.email if request.user.is_authenticated else "",
                action       = action,
                details      = details,
                target_type  = target_type,
                target_id    = str(target_id),
                target_label = target_label,
                ip_address   = _get_client_ip(request),
                user_agent   = request.META.get("HTTP_USER_AGENT", ""),
            )
        except Exception as e:
            logger.error(f"AdminAuditLogService.log failed: {e}")

    @staticmethod
    def get_logs(
        action=None,
        date_range=None,
        date_from=None,
        date_to=None,
        admin_id=None,
        search=None,
    ):
        from administrator.models import AdminAuditLog
        from django.db.models import Q
        from django.utils import timezone
        from datetime import timedelta

        qs = AdminAuditLog.objects.select_related("admin").all()

        if action:
            qs = qs.filter(action=action)

        if date_range:
            now = timezone.now()
            if date_range == "day":
                since = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif date_range == "week":
                since = now - timedelta(weeks=1)
            elif date_range == "month":
                since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            elif date_range == "year":
                since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                since = None
            if since:
                qs = qs.filter(created_at__gte=since)

        

        if date_from:
            parsed_from = parse_datetime(date_from)
            if parsed_from:
                qs = qs.filter(created_at__gte=parsed_from)

        if date_to:
            parsed_to = parse_datetime(date_to)
            if parsed_to:
                qs = qs.filter(created_at__lte=parsed_to)

        if admin_id:
            qs = qs.filter(admin_id=admin_id)

        if search:
            qs = qs.filter(
                Q(admin_email__icontains=search)  |
                Q(target_label__icontains=search) |
                Q(details__icontains=search)
            )

        return qs.order_by("-created_at")