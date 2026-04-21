import uuid

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User


class Admin(models.Model):
    user=models.OneToOneField(User, on_delete=models.CASCADE,related_name='admin_profile')
    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=50,default='admin')
    

    def __str__(self):
        return self.full_name
    


class AdminOTP(models.Model):
    """
    Stores a one-time password for admin two-factor login.
    Created after successful password verification.
    Consumed (marked used) after successful OTP verification.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(User,on_delete=models.CASCADE,related_name="admin_otps",)
    otp        = models.CharField(max_length=6)

    # Temporary token returned to the client after password check.
    # Client sends this back with the OTP to prove they are
    # continuing the same login session.
    temp_token = models.UUIDField(default=uuid.uuid4, unique=True)

    is_used    = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"OTP for {self.user.email} — {'used' if self.is_used else 'pending'}"



class FlaggedUser(models.Model):
    """
    Tracks users flagged by the system for suspicious activity.
    Created by the flag_suspicious_users Celery beat task.
    Admin can review and clear flags.
    """
    FLAG_REASON_CHOICES = [
        ("high_transaction_volume", "Unusually High Transaction Volume"),
        ("multiple_refunds",        "Multiple Refund Requests"),
        ("suspicious_pattern",      "Suspicious Purchase Pattern"),
        ("manual",                  "Manually Flagged by Admin"),
    ]
 
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user      = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="flag",
    )
    reason    = models.CharField(max_length=50, choices=FLAG_REASON_CHOICES)
    notes     = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)  # False = admin cleared the flag
    flagged_at = models.DateTimeField(auto_now_add=True)
    cleared_at = models.DateTimeField(null=True, blank=True)
    cleared_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="cleared_flags",
    )
 
    class Meta:
        ordering = ["-flagged_at"]
 
    def __str__(self):
        return f"{self.user.email} — {self.reason} — {'active' if self.is_active else 'cleared'}"


class AdminAuditLog(models.Model):
    """
    Immutable, append-only audit trail for all admin actions.
    Never deleted — use for compliance and accountability.
    """
 
    ACTION_CHOICES = [
        # User actions
        ("user_suspend",       "User Suspended"),
        ("user_unsuspend",     "User Unsuspended"),
        ("user_flag",          "User Flagged"),
        ("user_unflag",        "User Unflagged"),
        ("account_approval",   "Account Approval"),
 
        # Host actions
        ("host_suspend",       "Host Suspended"),
        ("host_unsuspend",     "Host Unsuspended"),
        ("host_approve",       "Host Verification Approved"),
        ("host_decline",       "Host Verification Declined"),
        ("badge_gifting",      "Badge Gifted to Host"),
        ("auto_payout",        "Auto Payout Enabled/Disabled"),
        ("force_payout",       "Force Payout Initiated"),
 
        # Event actions
        ("event_suspend",      "Event Suspended"),
        ("event_unsuspend",    "Event Unsuspended"),
        ("event_delete",       "Event Deleted"),
        ("event_feature",      "Event Featured"),
        ("event_pausing",      "Event Paused"),
 
        # Withdrawal / Financial actions
        ("withdrawal_approve", "Withdrawal Approved"),
        ("withdrawal_reject",  "Withdrawal Rejected"),
        ("account_suspension", "Account Suspension"),
        ("ban",                "User / Host Banned"),
 
        # General
        ("other",              "Other"),
    ]
 
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 
    # Who did it
    admin       = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    admin_email = models.EmailField()  # cached in case admin is deleted
 
    # What was done
    action  = models.CharField(max_length=30, choices=ACTION_CHOICES)
    details = models.TextField(blank=True)
 
    # Who/what it was done to
    target_type  = models.CharField(max_length=50, blank=True)   # "user" | "host" | "event" | "withdrawal"
    target_id    = models.CharField(max_length=100, blank=True)  # ID of target
    target_label = models.CharField(max_length=255, blank=True)  # human label e.g. email or event title
 
    # Network
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
 
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["-created_at"]
        db_table = "admin_audit_log"
 
    def __str__(self):
        return f"{self.admin_email} — {self.action} — {self.created_at:%Y-%m-%d %H:%M}"
 





class SystemConfig(models.Model):
    """
    Key-value store for all admin-configurable system settings.
    One row per config key — never delete, always update.
    Snapshot (previous_value) stored on every update for reset-to-last-saved.
 
    All settings live under logical groups (section field).
    """
 
    SECTION_CHOICES = [
        ("general",       "General"),
        ("policies",      "Policies"),
        ("fees",          "Fees & Commissions"),
        ("fraud",         "Fraud Detection"),
        ("notifications", "Notifications"),
        ("localization",  "Localization"),
    ]
 
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    section        = models.CharField(max_length=30, choices=SECTION_CHOICES)
    key            = models.CharField(max_length=100, unique=True)
    value          = models.JSONField()            # current value
    previous_value = models.JSONField(null=True, blank=True)  # last saved before current edit
    default_value  = models.JSONField()            # factory default — used for full reset
    label          = models.CharField(max_length=255, blank=True)  # human label for UI
    updated_at     = models.DateTimeField(auto_now=True)
    updated_by     = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="config_updates",
    )
 
    class Meta:
        ordering = ["section", "key"]
 
    def __str__(self):
        return f"{self.section}.{self.key} = {self.value}"
 
    @classmethod
    def get(cls, key, default=None):
        """Fast read helper."""
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default
 
    @classmethod
    def set(cls, key, value, user=None):
        """Updates value, saves current as previous_value."""
        obj, _ = cls.objects.get_or_create(
            key=key,
            defaults={
                "section":        "general",
                "value":          value,
                "default_value":  value,
            },
        )
        obj.previous_value = obj.value
        obj.value          = value
        obj.updated_by     = user
        obj.save(update_fields=["value", "previous_value", "updated_by", "updated_at"])
        return obj
 
    @classmethod
    def reset_to_last_saved(cls, keys):
        """Restores previous_value → value for given keys."""
        updated = []
        for obj in cls.objects.filter(key__in=keys):
            if obj.previous_value is not None:
                obj.value = obj.previous_value
                obj.save(update_fields=["value", "updated_at"])
                updated.append(obj.key)
        return updated
 
    @classmethod
    def reset_to_default(cls, keys=None):
        """Restores default_value → value. If keys=None, resets everything."""
        qs = cls.objects.all() if keys is None else cls.objects.filter(key__in=keys)
        updated = []
        for obj in qs:
            obj.previous_value = obj.value
            obj.value          = obj.default_value
            obj.save(update_fields=["value", "previous_value", "updated_at"])
            updated.append(obj.key)
        return updated
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Default seed data — run once after migration
# python manage.py shell
# from administrator.models import SystemConfig
# SystemConfigSeed.seed()
# ─────────────────────────────────────────────────────────────────────────────
 
class SystemConfigSeed:
 
    DEFAULTS = [
        # ── General ────────────────────────────────────────────────────────────
        {
            "section": "general",
            "key":     "platform_support_email",
            "value":   "inquiries@qavtix.com",
            "label":   "Platform Support Email",
        },
        {
            "section": "general",
            "key":     "default_currency",
            "value":   {"code": "USD", "label": "US Dollar"},
            "label":   "Default Currency",
        },
        {
            "section": "general",
            "key":     "default_timezone",
            "value":   "Africa/Lagos",
            "label":   "Default Timezone",
        },
 
        # ── Policies ────────────────────────────────────────────────────────────
        {
            "section": "policies",
            "key":     "seller_verification_required",
            "value":   True,
            "label":   "Seller Verification Required",
        },
        {
            "section": "policies",
            "key":     "auto_approve_listing",
            "value":   False,
            "label":   "Auto-Approve Listing",
        },
 
        # ── Fees ─────────────────────────────────────────────────────────────
        {
            "section": "fees",
            "key":     "ticket_resell_commission",
            "value":   25,
            "label":   "Ticket Resell Commission (%)",
        },
        {
            "section": "fees",
            "key":     "seller_service_fee",
            "value":   10,
            "label":   "Seller Service Fee (%)",
        },
        {
            "section": "fees",
            "key":     "buyer_service_fee",
            "value":   10,
            "label":   "Buyer Service Fee (%)",
        },
        {
            "section": "fees",
            "key":     "vat_enabled",
            "value":   False,
            "label":   "Tax/VAT Charges Enabled",
        },
        {
            "section": "fees",
            "key":     "prices_include_vat",
            "value":   False,
            "label":   "Default Pricing Includes VAT",
        },
        {
            "section": "fees",
            "key":      "vat_percentage",
            "value":    7.5,
            "label": "  VAT (%)",
        },
        
        # ── Fraud Detection ──────────────────────────────────────────────────
        {
            "section": "fraud",
            "key":     "fraud_sensitivity",
            "value":   "medium",
            "label":   "Fraud Detection Sensitivity",
        },
 
        # ── Notifications ────────────────────────────────────────────────────
        {
            "section": "notifications",
            "key":     "email_notifications",
            "value":   {
                "admin_alerts":      True,
                "fraud_alerts":      True,
                "high_volume_sales": False,
                "failed_payouts":    True,
            },
            "label": "Email Notification Preferences",
        },
        {
            "section": "notifications",
            "key":     "sms_notifications",
            "value":   {
                "admin_alerts":      False,
                "fraud_alerts":      True,
                "high_volume_sales": False,
                "failed_payouts":    False,
            },
            "label": "SMS Notification Preferences",
        },
 
        # ── Localization ─────────────────────────────────────────────────────
        {
            "section": "localization",
            "key":     "supported_countries",
            "value":   ["Ghana", "Nigeria", "South Africa","Kenya"],
            "label":   "Supported Countries",
        },
        {
            "section": "localization",
            "key":     "supported_currencies",
            "value":   ["GHS", "NGN", "ZAR", "USD","KES"],
            "label":   "Supported Currencies",
        },
        {
            "section": "localization",
            "key":     "language",
            "value":   "en",
            "label":   "Platform Language",
        },
        {
            "section": "localization",
            "key":     "date_time_format",
            "value":   "24h",
            "label":   "Date & Time Format",
        },
    ]
 
    @classmethod
    def seed(cls):
        from administrator.models import SystemConfig
        created_count = 0
        for item in cls.DEFAULTS:
            obj, created = SystemConfig.objects.get_or_create(
                key=item["key"],
                defaults={
                    "section":       item["section"],
                    "value":         item["value"],
                    "default_value": item["value"],
                    "label":         item.get("label", ""),
                },
            )
            if created:
                created_count += 1
        print(f"SystemConfig: {created_count} defaults seeded.")


class AutoPayout(models.Model):
    """
    Enable/disable automatic payout processing for a host.
    When enabled, withdrawals are processed automatically without admin approval.
    Payouts occur every Friday.
    """
    host = models.OneToOneField(
        'host.Host',
        on_delete=models.CASCADE,
        related_name='auto_payout'
    )
    
    # Enable/disable automatic payout
    is_enabled = models.BooleanField(default=False)
    
    # Last payout date for tracking
    last_payout_date = models.DateTimeField(null=True, blank=True)
    
    # Metadata for tracking failures
    metadata = models.JSONField(default=dict, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'transactions_auto_payout'
        verbose_name = 'Auto Payout Configuration'
        verbose_name_plural = 'Auto Payout Configurations'
    
    def __str__(self):
        status = 'Enabled' if self.is_enabled else 'Disabled'
        return f"AutoPayout({self.host.user.email}) - {status}"
    
    def to_dict(self):
        """Return serializable dict representation"""
        return {
            'id': str(self.id),
            'host_id': str(self.host.id),
            'host_email': self.host.user.email,
            'is_enabled': self.is_enabled,
            'last_payout_date': self.last_payout_date.isoformat() if self.last_payout_date else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
 