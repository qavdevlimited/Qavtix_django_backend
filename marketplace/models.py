# marketplace/models.py
from django.db import models
from django.contrib.auth import get_user_model
from transactions.models import IssuedTicket
from django.utils import timezone


User = get_user_model()

class MarketListing(models.Model):
    TICKET_STATUS_CHOICES = [
        ("active", "Active"),
        ("sold", "Sold"),
        ("cancelled", "Cancelled"),
    ]

    ticket = models.OneToOneField(
        IssuedTicket,
        on_delete=models.CASCADE,
        related_name="market_listing"
    )
    seller = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="market_listings"
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=TICKET_STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)  # Optional expiry for listing

    def mark_sold(self, buyer):
        """
        When a ticket is sold:
        - Update IssuedTicket owner
        - Update ticket status
        - Mark listing as sold
        """
        self.ticket.owner = buyer
        self.ticket.status = "resold"
        self.ticket.transferred_at = timezone.now()
        self.ticket.save()

        self.status = "sold"
        self.save()



class TicketTransferHistory(models.Model):
    ticket = models.ForeignKey(IssuedTicket, on_delete=models.CASCADE, related_name="transfer_history")
    from_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="transfers_from")
    to_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="transfers_to")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    transferred_at = models.DateTimeField(auto_now_add=True)