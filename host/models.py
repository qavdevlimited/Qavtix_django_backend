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
    business_type=models.CharField(max_length=50)
    registration_number=models.CharField(max_length=50)
    tax_id=models.CharField(max_length=50)
    phone_number= models.CharField(max_length=16)
    companies_email=models.EmailField(max_length=254)
    country=models.CharField(max_length=30)
    state=models.CharField(max_length=30)
    city=models.CharField(max_length=30)
    postal_code=models.CharField(max_length=20)
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