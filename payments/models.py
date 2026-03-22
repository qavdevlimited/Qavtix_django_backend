from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
import uuid

class PaymentCard(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="cards")
    provider = models.CharField(max_length=50)  # stripe or paystack
    token = models.CharField(max_length=255)  # payment method ID / token
    brand = models.CharField(max_length=50, null=True, blank=True)  # Visa, Mastercard
    last4 = models.CharField(max_length=4, null=True, blank=True)
    exp_month = models.IntegerField(null=True, blank=True)
    exp_year = models.IntegerField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return f"{self.provider.upper()} {self.brand or ''} ****{self.last4 or ''}"

class Payment(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email=models.EmailField(blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="payments",null=True)
    card = models.ForeignKey(PaymentCard, on_delete=models.SET_NULL, null=True, blank=True)
    provider = models.CharField(max_length=50)  # stripe or paystack
    provider_payment_id = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    status = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    # Generic relation to connect to any object (Order, FeaturedEvent)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True)
    object_id = models.UUIDField(null=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    metadata = models.JSONField(null=True, blank=True)


class SplitPayment(models.Model):
    order = models.ForeignKey("transactions.Order", on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    percentage = models.FloatField()
    status = models.BooleanField(default=False)



class PayoutInformation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="payout_accounts"
    )

    bank_name = models.CharField(max_length=150)
    account_name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=20)

    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    

    def __str__(self):
        return f"{self.user.username} - {self.bank_name}"
    


class HostPlan(models.Model):
    PLAN_CHOICES = [
        ("free",       "Free"),
        ("pro",        "Pro"),
        ("enterprise", "Enterprise"),
    ]
    BILLING_CHOICES = [
        ("monthly", "Monthly"),
        ("annual",  "Annual"),
    ]

    slug          = models.CharField(max_length=20, choices=PLAN_CHOICES, unique=True)
    name          = models.CharField(max_length=50)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2)
    annual_price  = models.DecimalField(max_digits=10, decimal_places=2)
    features      = models.JSONField(default=dict)  # shown on pricing page
    is_active     = models.BooleanField(default=True)

    def __str__(self):
        return self.name