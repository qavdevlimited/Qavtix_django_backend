# attendee/mixins.py

from rest_framework.exceptions import PermissionDenied
from django.utils.decorators import method_decorator
from functools import wraps

from .plan_limits import (
    get_attendee_plan_slug,
    has_attendee_feature,
    which_attendee_plan_unlocks,
)


def require_attendee_feature(feature: str, upgrade_message=None):
    """
    Decorator to block non-Pro attendees from using promo codes or other features.
    
    Usage:
        @require_attendee_feature("promo_codes")
        class ValidatePromoCodeView(APIView):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(view, request, *args, **kwargs):
            attendee = getattr(request.user, 'attendee_profile', None)
            if not attendee:
                raise PermissionDenied({"message": "Attendee profile required."})

            plan_slug = get_attendee_plan_slug(attendee)

            if not has_attendee_feature(plan_slug, feature):
                upgrade_to = which_attendee_plan_unlocks(feature)
                raise PermissionDenied({
                    "message": upgrade_message or (
                        f"Promo codes are not available on your current plan. "
                        f"Upgrade to {upgrade_to.capitalize()} to use promo codes."
                    ),
                    "feature":     feature,
                    "your_plan":   plan_slug,
                    "upgrade_to":  upgrade_to,
                })

            return view_func(view, request, *args, **kwargs)
        return _wrapped_view
    return decorator