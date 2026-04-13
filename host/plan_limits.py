# host/plan_limits.py

PLAN_LIMITS = {
    "free": {
        # Events
        "max_active_events":     2,
        "max_ticket_types":      1,       # single ticket type only
        "advanced_event_setup":  False,   # basic setup only

        # Promo codes
        "promo_codes":           False,
        "promo_code_limit":      0,

        # Referral / affiliate
        "affiliate":             False,

        # Team
        "team_permissions":      0,       # no team members

        # Attendees
        "attendee_export_limit": 250,

        # QR Check-in
        "qr_checkin":            False,

        # Analytics
        "sales_insights":        True,    # basic real-time only
        "revenue_chart":         False,
        "geo_breakdown":         False,
        "week_analysis":         False,

        # Marketing
        "marketing_dashboard":   False,
        "email_campaigns":       False,
        "email_campaign_limit":  0,
        "sms_campaign_limit":    0, 
        "sms_campaigns":    False,
        "sponsored_campaigns":   False,

        # Featured
        "featured_listing":      False,   # must pay separately

        # Finance
        "bulk_refunds":          False,

        # Security / fraud
        "fraud_detection":       True,    # basic fraud detection
        "resale_controls":       False,
        "advanced_security":     False,

        # Support
        "priority_support":      False,
        "dedicated_manager":     False,

        # Group sharing
        "group_sharing":         False,

        "customer_profile_insights": True,

        "event_ticket_limit":       750,     # max tickets per event
    },

    "pro": {
        # Events
        "max_active_events":     None,    # unlimited
        "max_ticket_types":      None,    # unlimited
        "advanced_event_setup":  True,

        # Promo codes
        "promo_codes":           True,
        "promo_code_limit":      100,

        # Referral / affiliate
        "affiliate":             True,

        # Team
        "team_permissions":      1,       # 1 team member

        # Attendees
        "attendee_export_limit": 1000,

        # QR Check-in
        "qr_checkin":            True,

        # Analytics
        "sales_insights":        True,
        "revenue_chart":         False,   # enterprise only
        "geo_breakdown":         False,   # enterprise only
        "week_analysis":         False,   # enterprise only

        # Marketing
        "marketing_dashboard":   True,
        "email_campaigns":       True,
        "email_campaign_limit":  400,
        "sms_campaign_limit":    0, 
        "sms_campaigns":    False,
        "sponsored_campaigns":   False,   # enterprise only

        # Featured
        "featured_listing":      False,   # enterprise only (2 weeks free)

        # Finance
        "bulk_refunds":          False,   # enterprise only

        # Security / fraud
        "fraud_detection":       True,
        "resale_controls":       False,   # enterprise only
        "advanced_security":     False,   # enterprise only

        # Support
        "priority_support":      True,    # priority email support
        "dedicated_manager":     False,   # enterprise only

        "customer_profile_insights": True,

        "event_ticket_limit":       2500,
    },

    "enterprise": {
        # Events
        "max_active_events":     None,    # unlimited
        "max_ticket_types":      None,    # unlimited
        "advanced_event_setup":  True,

        # Promo codes
        "promo_codes":           True,
        "promo_code_limit":      500,

        # Referral / affiliate
        "affiliate":             True,

        # Team
        "team_permissions":      3,       # 3 team members

        # Attendees
        "attendee_export_limit": None,    # unlimited

        # QR Check-in
        "qr_checkin":            True,

        # Analytics
        "sales_insights":        True,
        "revenue_chart":         True,
        "geo_breakdown":         True,
        "week_analysis":         True,

        # Marketing
        "marketing_dashboard":   True,
        "email_campaigns":       True,
        "email_campaign_limit":  4600,     # same as pro — 100 sends/month
        "sms_campaign_limit":    100, 
        "sms_campaigns":    True,
        "sponsored_campaigns":   True,

        # Featured
        "featured_listing":      True,    # 2 weeks free included

        # Finance
        "bulk_refunds":          True,

        # Security / fraud
        "fraud_detection":       True,
        "resale_controls":       True,
        "advanced_security":     True,

        # Support
        "priority_support":      True,    # priority customer support
        "dedicated_manager":     True,

        "customer_profile_insights": True,

        "event_ticket_limit":       None,    # unlimited
    },
}


def get_host_plan_slug(host) -> str:
    from django.utils import timezone

    sub = (
        host.subscriptions
        .filter(status__in=["active", "cancelled"])  # ← include cancelled
        .order_by("-started_at")
        .first()
    )

    if not sub:
        return "free"

    if sub.expires_at and timezone.now() > sub.expires_at:
        return "free"

    return sub.plan_slug


def has_feature(plan_slug: str, feature: str) -> bool:
    """Returns True if plan has access to a boolean feature."""
    plan  = PLAN_LIMITS.get(plan_slug, PLAN_LIMITS["free"])
    value = plan.get(feature, False)
    return bool(value)


def get_limit(plan_slug: str, feature: str):
    """
    Returns the numeric limit for a feature.
    None = unlimited, 0 = blocked.
    """
    plan = PLAN_LIMITS.get(plan_slug, PLAN_LIMITS["free"])
    return plan.get(feature, 0)


def which_plan_unlocks(feature: str) -> str:
    """Returns the lowest plan tier that unlocks a feature."""
    for slug in ("pro", "enterprise"):
        if has_feature(slug, feature):
            return slug
    return "enterprise"