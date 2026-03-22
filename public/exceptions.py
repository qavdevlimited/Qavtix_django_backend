from rest_framework.views import exception_handler
from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, PermissionDenied
from authentication.utils import flatten_errors_login


def custom_exception_handler(exc, context):
    """
    Global DRF exception handler that wraps errors into a consistent response format.
    """
    response = exception_handler(exc, context)

    if response is not None:
        raw = response.data

        # ── Plan limit / feature block ────────────────────────────────────────
        # When PlanFeatureMixin raises PermissionDenied(detail={...}),
        # response.data is {"detail": {"message": ..., "feature": ..., ...}}
        # We extract the inner dict and return it as structured data.
        if isinstance(exc, PermissionDenied) and isinstance(raw.get("detail"), dict):
            inner = raw["detail"]
            response.data = {
                "status":  403,
                "message": inner.get("message", "Permission denied."),
                "data":    {k: v for k, v in inner.items() if k != "message"},
            }
            return response

        # ── All other errors — existing logic unchanged ───────────────────────
        message = raw

        if isinstance(message, dict):
            message = flatten_errors_login(message)
        elif isinstance(message, list):
            message = "; ".join(str(m) for m in message)
        else:
            message = str(message)

        if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
            status_code = 401
        elif isinstance(exc, PermissionDenied):
            status_code = 403
        else:
            status_code = response.status_code

        response.data = {
            "status":  status_code,
            "message": message,
            "data":    None,
        }

    return response