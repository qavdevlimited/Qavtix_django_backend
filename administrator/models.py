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
 