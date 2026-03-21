import uuid

from django.db import models
from public.models import Category
from django.conf import settings






class Host(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="host_profile"
    )
    full_name=models.CharField(max_length=50)
    description=models.TextField(max_length=5000,default="No Description")
    business_name=models.CharField(max_length=100)
    business_type=models.CharField(max_length=50, blank=True, null=True)
    registration_number=models.CharField(max_length=50, blank=True, null=True)
    tax_id=models.CharField(max_length=50, blank=True, null=True)
    phone_number= models.CharField(max_length=16)
    country=models.CharField(max_length=30)
    state=models.CharField(max_length=30)
    city=models.CharField(max_length=30)
    postal_code=models.CharField(max_length=20, blank=True, null=True)
    relevant_links = models.JSONField(default=list, blank=True)
    categories = models.ManyToManyField(Category,related_name="hosts", blank=True)
    registration_date=models.DateTimeField(auto_now_add=True)
    agree_to_terms=models.BooleanField(default=False)
    role=models.CharField(max_length=20, default="host")
    followers=models.IntegerField(default=0)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.full_name
    



class HostLink(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="links"
    )
    url = models.URLField(max_length=200)
    label = models.CharField(max_length=50, blank=True)  # e.g. Twitter, Website
    created_at = models.DateTimeField(auto_now_add=True)



class EmailCampaign(models.Model):

    STATUS_CHOICES = (
        ("draft",     "Draft"),
        ("scheduled", "Scheduled"),
        ("sent",      "Sent"),
        ("failed",    "Failed"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    host  = models.ForeignKey(Host,  on_delete=models.CASCADE, related_name="email_campaigns")
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="email_campaigns")

    # Campaign identity
    campaign_name = models.CharField(max_length=255)
    subject       = models.CharField(max_length=255)
    html_content  = models.TextField(help_text="Full HTML body of the email.")

    # Sender info (can default to event organizer details)
    sender_name  = models.CharField(max_length=255)
    sender_email = models.EmailField()

    # Brevo references — populated after syncing / sending
    brevo_list_id     = models.IntegerField(null=True, blank=True)
    brevo_campaign_id = models.IntegerField(null=True, blank=True)

    # Recipients snapshot — recorded at send time
    recipients_count = models.PositiveIntegerField(default=0)

    # Cached Brevo stats — refreshed on list fetch
    open_rate  = models.FloatField(default=0.0)
    click_rate = models.FloatField(default=0.0)

    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    sent_at    = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.campaign_name} — {self.event.title}"



class CheckIn(models.Model):

    STATUS_CHOICES = [
        ("checked_in", "Checked In"),
        ("duplicate",  "Duplicate Scan"),
        ("invalid",    "Invalid"),
    ]

    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issued_ticket = models.OneToOneField(
        "transactions.IssuedTicket",
        on_delete=models.CASCADE,
        related_name="checkin",
        null=True,      # null when status=invalid (ticket not found)
        blank=True,
    )

    # Raw token stored for audit/log purposes
    scanned_token = models.TextField()

    status        = models.CharField(max_length=20, choices=STATUS_CHOICES)
    checked_in_at = models.DateTimeField(auto_now_add=True)

    # Who performed the scan (staff/host account), optional
    scanned_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="checkins_performed",
    )

    notes = models.TextField(blank=True)   # e.g. reason for duplicate/invalid

    class Meta:
        ordering = ["-checked_in_at"]

    def __str__(self):
        return f"CheckIn {self.id} — {self.status}"




class HostActivity(models.Model):
    """
    Activity feed for the host dashboard.
    Created programmatically whenever a relevant event occurs
    (sale completed, check-in, refund, etc.)
    """

    ACTIVITY_TYPES = [
        ("sale",         "Sale"),
        ("checkin",      "Check-In"),
        ("refund",       "Refund"),
        ("withdrawal",   "Withdrawal"),
        ("ticket_transfer", "Ticket Transfer"),
    ]

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="host_activities",
    )
    activity_type = models.CharField(max_length=30, choices=ACTIVITY_TYPES)
    message       = models.TextField()   # human-readable e.g. "John bought 2x VIP — ₦30,000"
    metadata      = models.JSONField(default=dict, blank=True)  # extra data for FE if needed
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.activity_type} — {self.created_at:%Y-%m-%d %H:%M}"


class HostNotification(models.Model):
    """
    Notifications for the host.
    """

    NOTIFICATION_TYPES = [
        ("sale",       "New Sale"),
        ("withdrawal", "Withdrawal Update"),
        ("checkin",    "Check-In Alert"),
        ("system",     "System"),
        ("refund",     "Refund"),
    ]

    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host     = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="host_notifications",
    )
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    title             = models.CharField(max_length=255)
    message           = models.TextField()
    is_read           = models.BooleanField(default=False)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.notification_type} — {self.title}"
