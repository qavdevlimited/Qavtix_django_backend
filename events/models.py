from django.db import models
from public.models import Category
import uuid
from django.contrib.auth.models import User
from host.models import Host
from django.utils import timezone

class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name



class Event(models.Model):

    EVENT_TYPE_CHOICES = (
        ("single", "Single Event"),
        ("recurring", "Recurring Event"),
    )

    LOCATION_TYPE_CHOICES = (
        ("physical", "Physical Venue"),
        ("online", "Online Event"),
        ("tba", "To Be Announced"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Basics
    title = models.CharField(max_length=255)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    tags = models.ManyToManyField("Tag", blank=True)

    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()

    # Location Type
    location_type = models.CharField(max_length=20, choices=LOCATION_TYPE_CHOICES)

    # Description
    short_description = models.CharField(max_length=160)
    full_description = models.TextField(max_length=5000)

    # Organizer Info Snapshot
    organizer_display_name = models.CharField(max_length=255)
    organizer_description = models.TextField(max_length=500, blank=True)
    public_email = models.EmailField()
    phone_number = models.CharField(max_length=20, blank=True)

    # Refund
    REFUND_CHOICES = (
        ("no", "No Refund"),
        ("partial", "Partial"),
        ("full", "Full"),
        ("custom", "Custom"),
    )

    refund_policy = models.CharField(max_length=20, choices=REFUND_CHOICES)
    refund_percentage = models.PositiveIntegerField(null=True, blank=True)

    # Check-in
    qr_enabled = models.BooleanField(default=True)
    age_restriction = models.BooleanField(default=False)

    # Email Notifications
    order_confirmation = models.BooleanField(default=True)
    ticket_delivery = models.BooleanField(default=True)
    reminders = models.BooleanField(default=False)
    post_event_emails = models.BooleanField(default=False)
    customize_sender_name = models.BooleanField(default=False)

    # Affiliate
    affiliate_enabled = models.BooleanField(default=False)
    commission_percentage = models.DecimalField( max_digits=5, decimal_places=2, null=True, blank=True)
    affiliate_start = models.DateTimeField(null=True, blank=True)
    affiliate_end = models.DateTimeField(null=True, blank=True)
    is_scheduled  = models.BooleanField(default=False)
    schedule_time = models.DateTimeField(null=True, blank=True)
    minimum_age = models.PositiveIntegerField(null=True, blank=True)

    currency = models.CharField(max_length=10, default="NGN")

    host= models.ForeignKey(
        Host,
        on_delete=models.CASCADE,
        related_name="hoster"
    )

    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("active", "Active"),
        ("sold-out", "Sold-Out"),
        ("ended", "Ended"),
        ("cancelled", "Cancelled"),
        ("banned", "Banned"),
        ("suspended","Suspended")
    )

    status= models.CharField(max_length=20, choices=STATUS_CHOICES,default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at =models.DateTimeField(auto_now=True)

    views_count = models.PositiveIntegerField(default=0)
    saves_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title

    def get_current_or_next_occurrence(self):
        from django.utils import timezone

        now = timezone.now()

        return self.occurrences.filter(
            start_datetime__gte=now
        ).order_by("start_datetime").first()

    def get_effective_start_datetime(self):
        if self.event_type == "recurring":
            occ = self.get_current_or_next_occurrence()
            if occ:
                return occ.start_datetime
        return self.start_datetime

    def get_effective_end_datetime(self):
        if self.event_type == "recurring":
            occ = self.get_current_or_next_occurrence()
            if occ:
                return occ.end_datetime
        return self.end_datetime

    # optional convenience
    @property
    def effective_start_datetime(self):
        return self.get_effective_start_datetime()

    @property
    def effective_end_datetime(self):
        return self.get_effective_end_datetime()

class EventOccurrence(models.Model):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="recurring_dates"
    )

    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()

    class Meta:
        ordering = ["start_datetime"]

    def __str__(self):
        return f"{self.event.title} ({self.start_datetime} - {self.end_datetime})"



class EventLocation(models.Model):
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name="event_location")

    venue_name = models.CharField(max_length=255, blank=True)
    address = models.TextField(blank=True)
    country = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.event.title} Location"


class EventMedia(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="media")

    image_url = models.URLField(null=True, blank=True)
    video_url = models.URLField(null=True, blank=True)

    is_featured = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.event.title} Media"



class OrganizerSocialLink(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="social_links")
    url = models.URLField()

    def __str__(self):
        return self.url


class Ticket(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tickets")

    ticket_type = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()
    per_person_max = models.PositiveIntegerField()

    sold_count=models.PositiveIntegerField(default=0)

    sales_start = models.DateTimeField()
    sales_end = models.DateTimeField()

    def __str__(self):
        return f"{self.event.title} - {self.ticket_type}"


class PromoCode(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="promo_codes")

    code = models.CharField(max_length=50)
    discount_percentage = models.PositiveIntegerField()
    maximum_users = models.PositiveIntegerField()
    valid_till = models.DateField()

    def __str__(self):
        return self.code


class EventPermission(models.Model):

    ROLE_CHOICES = (
        ("host", "Host"),
        ("collaborator", "Collaborator"),
        ("financial", "Financial"),
    )

    STATUS_CHOICES = (
        ("active", "Active"),
        ("disabled", "Disabled"),
        ("pending", "Pending Invitation"),
    )

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="permissions")
    email = models.EmailField()

    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,default='pending')

    def __str__(self):
        return f"{self.email} - {self.role}"
