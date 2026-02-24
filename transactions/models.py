import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from events.models import Event,Ticket
from attendee.models import PayoutInformation

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


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("refunded", "Refunded"),
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
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    STATUS_CHOICES = [
        ("active", "Active"),
        ("transferred", "Transferred"),
        ("resold", "Resold"),
        ("used", "Used"),
        ("cancelled", "Cancelled"),
    ]

    order_ticket = models.ForeignKey(
        OrderTicket,
        on_delete=models.CASCADE,
        related_name="issued_tickets"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="owned_tickets"
    )

    original_owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="original_tickets"
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    transferred_at = models.DateTimeField(null=True, blank=True)
    metadata=models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)




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
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True)

    def __str__(self):
        return f"{self.user.username} - {self.amount}"