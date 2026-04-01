# attendee/plan_limits.py

from django.utils import timezone

ATTENDEE_PLAN_LIMITS = {
    "free": {
        "promo_codes": False,          
        "higher_discount_caps": False,
        "early_access": False,
        "exclusive_deals": False,
        "boosted_affiliate": False,
    },
    "pro": {
        "promo_codes": True,
        "higher_discount_caps": True,
        "early_access": True,
        "exclusive_deals": True,
        "boosted_affiliate": True,
    }
}


def get_attendee_plan_slug(attendee):
    """Get current valid plan for attendee (handles cancelled but not expired)"""
    sub = (
        attendee.subscriptions
        .filter(status__in=["active", "cancelled"])
        .order_by("-started_at")
        .first()
    )

    if not sub:
        return "free"

    # If expired → free
    if sub.expires_at and timezone.now() > sub.expires_at:
        return "free"

    return sub.plan_slug


def has_attendee_feature(plan_slug: str, feature: str) -> bool:
    plan = ATTENDEE_PLAN_LIMITS.get(plan_slug, ATTENDEE_PLAN_LIMITS["free"])
    return bool(plan.get(feature, False))


def which_attendee_plan_unlocks(feature: str) -> str:
    for slug in ("pro", "enterprise"):
        if has_attendee_feature(slug, feature):
            return slug
    return "pro"