import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from events.models import Event,Ticket
from payments.models import PayoutInformation

class FeaturedEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="featured")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField()
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending"),
            ("active", "Active"),
            ("expired", "Expired"),
            ("cancelled", "Cancelled")
        ],
        default="pending"
    )
    metadata = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.event.title} featured by {self.user.username}"
    


class FeaturedPlan(models.Model):
    """
    Available featured event pricing tiers.
    Admin manages these — no code changes needed to update prices.
    """
 
    PLAN_CHOICES = [
        ("basic",    "Basic"),
        ("standard", "Standard"),
        ("advanced", "Advanced"),
        ("premium",  "Premium"),
    ]
 
    slug           = models.CharField(max_length=20, choices=PLAN_CHOICES, unique=True)
    name           = models.CharField(max_length=50)
    duration_days  = models.PositiveIntegerField()
    price          = models.DecimalField(max_digits=10, decimal_places=2)
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    features       = models.JSONField(default=list)
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        ordering = ["duration_days"]
 
    def __str__(self):
        return f"{self.name} — ₦{self.price} / {self.duration_days} day(s)"
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Seed data — run once in shell after migration:
# from transactions.models import FeaturedPlan, FEATURED_PLANS_SEED
# for p in FEATURED_PLANS_SEED:
#     FeaturedPlan.objects.get_or_create(slug=p["slug"], defaults=p)
# ─────────────────────────────────────────────────────────────────────────────
 
FEATURED_PLANS_SEED = [
    {
        "slug": "basic", "name": "Basic", "duration_days": 1,
        "price": 45000, "original_price": 50000,
        "features": [
            "Featured in Top Events for 24 hours",
            "Priority placement in event feed",
            '"Featured" badge on your post',
        ],
    },
    {
        "slug": "standard", "name": "Standard", "duration_days": 3,
        "price": 85000, "original_price": 130000,
        "features": [
            "Featured for 72 hours",
            "Higher visibility across homepage & search",
            "Featured badge + boosted impressions",
            "Social media story promotion",
        ],
    },
    {
        "slug": "advanced", "name": "Advanced", "duration_days": 7,
        "price": 165000, "original_price": 300000,
        "features": [
            "Featured for 7 days",
            "Maximum visibility & sustained reach",
            "Featured badge + boosted impressions",
            "Weekly main social media post + story promotion",
            "Performance insights",
        ],
    },
    {
        "slug": "premium", "name": "Premium", "duration_days": 30,
        "price": 600000, "original_price": 1300000,
        "features": [
            "Featured for 30 days",
            "Dominant visibility across homepage, event feed & search",
            "Featured badge + continuous boosted impressions",
            "Monthly main social media post + story promotion",
            "Email / newsletter feature",
            "Advanced performance insights & engagement analytics",
        ],
    },
]
 


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("refunded", "Refunded"),
        ("expired", "Expired"), 
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name=models.CharField(max_length=300, blank=True)
    phone_number=models.CharField(default="09000001111")
    user = models.ForeignKey(User, on_delete=models.CASCADE,null=True)
    email=models.EmailField(blank=True)
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    fees = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(blank=True, null=True) 
    is_split=models.BooleanField(default=False) 
    vat  =  models.DecimalField(max_digits=10, decimal_places=2, default=0)
    marketplace_listing = models.ForeignKey(
        "marketplace.MarketListing",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )


    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order {self.id} for {self.event.title}"
    

class OrderTicket(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="tickets")
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def subtotal(self):
        return self.quantity * self.price


class IssuedTicket(models.Model):
    STATUS_CHOICES = [
        ("active",      "Active"),
        ("transferred", "Transferred"),
        ("resold",      "Resold"),
        ("used",        "Used"),
        ("cancelled",   "Cancelled"),
        ("reserved",    "Reserved"),   # ← NEW: locked during split, not yet issued
    ]

    order        = models.ForeignKey("Order", on_delete=models.CASCADE)
    order_ticket = models.ForeignKey(
        "OrderTicket",
        on_delete=models.CASCADE,
        related_name="issued_tickets"
    )
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE)

    # Authenticated owner — null for guests
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="owned_tickets",
        null=True,
        blank=True,
    )

    # Guest owner — filled when buyer is not registered
    guest_email = models.EmailField(blank=True)

    original_owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="original_tickets"
    )
    # Guest original owner
    guest_original_email = models.EmailField(blank=True)

    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    transferred_at = models.DateTimeField(null=True, blank=True)
    metadata       = models.JSONField(default=dict)
    created_at     = models.DateTimeField(auto_now_add=True)

    def get_owner_email(self):
        if self.owner:
            return self.owner.email
        return self.guest_email

    def __str__(self):
        return f"Ticket {self.id} — {self.get_owner_email()}"





class TicketTransferHistory(models.Model):
    ticket = models.ForeignKey(IssuedTicket, on_delete=models.CASCADE, related_name="transfer_history")
    from_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="transfers_from")
    to_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="transfers_to")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    transferred_at = models.DateTimeField(auto_now_add=True)




class Withdrawal(models.Model):

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("paid", "Paid"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="withdrawals"
    )

    payout_account = models.ForeignKey(
        PayoutInformation,
        on_delete=models.PROTECT
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True)

    def __str__(self):
        return f"{self.user.username} - {self.amount}"




class Refund(models.Model):

    REASON_CHOICES = [
        ("cancelled_event", "Event Cancelled"),
        ("customer_request", "Customer Request"),
        ("duplicate_order", "Duplicate Order"),
        ("fraud",           "Fraud"),
        ("other",           "Other"),
    ]

    STATUS_CHOICES = [
        ("pending",   "Pending"),
        ("approved",  "Approved"),
        ("rejected",  "Rejected"),
        ("processed", "Processed"),
    ]

    id    = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.OneToOneField(
        "Order",
        on_delete=models.CASCADE,
        related_name="refund",
    )

    amount     = models.DecimalField(max_digits=12, decimal_places=2)
    reason     = models.CharField(max_length=30, choices=REASON_CHOICES)
    notes      = models.TextField(blank=True)
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # Who processed it (admin/host user)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="processed_refunds",
    )

    created_at   = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund {self.id} — {self.order.id} — {self.status}"
    



# transactions/models.py — ADD these models to your existing file

import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class SplitOrder(models.Model):
    """
    Tracks an overall split payment session.
    Created when initiator checks out with is_split=True.
    Order only completes when ALL participants have paid.
    """
    STATUS_CHOICES = [
        ("pending",   "Pending"),     # waiting for all to pay
        ("completed", "Completed"),   # all paid, tickets issued
        ("expired",   "Expired"),     # time ran out, refunds created
        ("cancelled", "Cancelled"),   # manually cancelled
    ]

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order       = models.OneToOneField(
        "Order",
        on_delete=models.CASCADE,
        related_name="split_order"
    )
    initiated_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="initiated_splits"
    )
    total_participants = models.PositiveIntegerField()  # must equal ticket quantity
    paid_count         = models.PositiveIntegerField(default=0)
    status             = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    expires_at         = models.DateTimeField()
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"SplitOrder {self.id} — {self.status}"

    def is_expired(self):
        return timezone.now() > self.expires_at and self.status == "pending"

    def check_completion(self):
        """Call after each participant pays. Completes order if all paid."""
        if self.paid_count >= self.total_participants:
            self.status = "completed"
            self.save(update_fields=["status"])
            return True
        return False


class SplitParticipant(models.Model):
    """
    One row per person in a split order (including the initiator).
    """
    STATUS_CHOICES = [
        ("pending",  "Pending"),   # hasn't paid yet
        ("paid",     "Paid"),      # paid successfully
        ("refunded", "Refunded"),  # refunded after cancellation
        ("failed",   "Failed"),    # payment failed
    ]

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    split_order = models.ForeignKey(
        SplitOrder,
        on_delete=models.CASCADE,
        related_name="participants"
    )
    user        = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="split_participations"
    )
    # The ticket reserved for this participant
    issued_ticket = models.OneToOneField(
        "IssuedTicket",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="split_participant"
    )

    amount          = models.DecimalField(max_digits=10, decimal_places=2)
    percentage      = models.DecimalField(max_digits=5, decimal_places=2)  # e.g. 33.33
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # Payment tracking
    payment_reference = models.CharField(max_length=255, blank=True)  # Paystack reference
    payment          = models.ForeignKey(
        "payments.Payment",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="split_participant"
    )

    # Payment link token — sent via email, used to identify participant on pay
    pay_token   = models.UUIDField(default=uuid.uuid4, unique=True)
    paid_at     = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("split_order", "user")

    def __str__(self):
        return f"{self.user.email} — {self.status} — {self.amount}"