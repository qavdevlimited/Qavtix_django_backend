# payments/serializers.py
from rest_framework import serializers
from decimal import Decimal
from payments.models import PaymentCard, Payment
from events.models import Ticket
from datetime import date


class TicketLineItemSerializer(serializers.Serializer):
    ticket_id = serializers.IntegerField()
    quantity  = serializers.IntegerField(min_value=1)


class SplitMemberSerializer(serializers.Serializer):
    email      = serializers.EmailField()
    percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    date_of_birth = serializers.DateField(required=False, allow_null=True)


class CheckoutSerializer(serializers.Serializer):

    # Buyer info
    full_name    = serializers.CharField()
    phone_number = serializers.CharField()
    email        = serializers.EmailField(required=False)  # required for guests

    # Flow selector
    is_split               = serializers.BooleanField(default=False)
    event_id               = serializers.UUIDField(required=False, allow_null=True)
    marketplace_listing_id = serializers.IntegerField(required=False, allow_null=True)

    # Tickets
    tickets    = TicketLineItemSerializer(many=True, required=False, default=list)
    promo_code = serializers.CharField(required=False, allow_blank=True, default="")

    # Card
    save_card = serializers.BooleanField(default=False)

    # Split members — only used when is_split=True
    split_members = SplitMemberSerializer(many=True, required=False, default=list)
    affiliate_code = serializers.UUIDField(required=False, allow_null=True)

    date_of_birth = serializers.DateField(required=False)

    def validate(self, data):
        marketplace_id = data.get("marketplace_listing_id")
        event_id       = data.get("event_id")
        tickets        = data.get("tickets", [])
        is_split       = data.get("is_split", False)

        # Must choose one flow
        if marketplace_id and (event_id or tickets):
            raise serializers.ValidationError(
                "Provide either marketplace_listing_id OR event_id with tickets, not both."
            )

        if not marketplace_id and not (event_id and tickets):
            raise serializers.ValidationError(
                "Provide either marketplace_listing_id OR event_id with tickets."
            )

        # Split validation
        if is_split:
            split_members = data.get("split_members", [])
            if not split_members:
                raise serializers.ValidationError(
                    "split_members is required when is_split=True."
                )
            if marketplace_id:
                raise serializers.ValidationError(
                    "Split payment is not available for marketplace purchases."
                )
        if event_id:
            from events.models import Event

            try:
                event = Event.objects.get(id=event_id)
            except Event.DoesNotExist:
                raise serializers.ValidationError("Event not found.")

            if event.age_restriction:
                if not is_split:
                    # ← NORMAL FLOW (unchanged)
                    dob = data.get("date_of_birth")

                    if not dob:
                        raise serializers.ValidationError(
                            {"date_of_birth": "This event requires your date of birth."}
                        )

                    today = date.today()
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

                    if age < event.minimum_age if event.minimum_age is not None else 18:
                        raise serializers.ValidationError(
                            {"date_of_birth": "You must reach the approved age to purchase tickets for this event."}
                        )

        return data


class CompleteCheckoutSerializer(serializers.Serializer):
    reference = serializers.CharField()
    save_card = serializers.BooleanField(default=False)
    country   = serializers.CharField(default="NG")
    email     = serializers.EmailField(required=False)  # for guests


class SplitPayTokenSerializer(serializers.Serializer):
    """Used by participants clicking their payment link."""
    pay_token = serializers.UUIDField()

# In your serializers file
class PaystackIntentSerializer(serializers.Serializer):
    event_id   = serializers.UUIDField()
    tickets    = TicketLineItemSerializer(many=True)
    promo_code = serializers.CharField(required=False, allow_blank=True)
    currency   = serializers.CharField(default="NGN")
    email      = serializers.EmailField(required=False)  # for guests


class PaymentCardSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentCard
        fields = [
            "id",
            "provider",
            "brand",
            "last4",
            "exp_month",
            "exp_year",
            "is_default",
        ]

#
class PaymentSerializer(serializers.ModelSerializer):
    card = PaymentCardSerializer(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "provider",
            "amount",
            "currency",
            "status",
            "card",
            "created_at",
        ]


class AddCardInitiateSerializer(serializers.Serializer):
    country  = serializers.CharField(default="NG")
    currency = serializers.CharField(default="NGN")
 
 
class AddCardConfirmSerializer(serializers.Serializer):
    reference   = serializers.CharField()
    country     = serializers.CharField(default="NG")
    set_default = serializers.BooleanField(default=True)
 



class TicketLineItemSerializer(serializers.Serializer):
    ticket_id = serializers.IntegerField()
    quantity  = serializers.IntegerField(min_value=1)
 
 
class CardCheckoutSerializer(serializers.Serializer):
    # Gateway
    country  = serializers.CharField(default="NG")
    currency = serializers.CharField(default="NGN")
 
    # Buyer info
    full_name    = serializers.CharField()
    phone_number = serializers.CharField()
 
    # Saved card — required
    card_id = serializers.UUIDField()
 
    # Normal purchase fields
    event_id   = serializers.UUIDField(required=False, allow_null=True)
    tickets    = TicketLineItemSerializer(many=True, required=False, default=list)
    promo_code = serializers.CharField(required=False, allow_blank=True, default="")
 
    # Affiliate
    affiliate_code = serializers.UUIDField(required=False, allow_null=True)
 
    # Marketplace purchase
    marketplace_listing_id = serializers.IntegerField(required=False, allow_null=True)
 
    def validate(self, data):
        marketplace_id = data.get("marketplace_listing_id")
        event_id       = data.get("event_id")
        tickets        = data.get("tickets", [])
 
        if marketplace_id and (event_id or tickets):
            raise serializers.ValidationError(
                "Provide either marketplace_listing_id OR event_id with tickets, not both."
            )
 
        if not marketplace_id and not (event_id and tickets):
            raise serializers.ValidationError(
                "Provide either marketplace_listing_id OR event_id with tickets."
            )
 
        return data
 


class HostPlanSerializer(serializers.Serializer):
    """Read-only — returned when listing available plans."""
    slug          = serializers.CharField()
    name          = serializers.CharField()
    monthly_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    annual_price  = serializers.DecimalField(max_digits=10, decimal_places=2)
    features      = serializers.DictField()


class SubscribeInitiateSerializer(serializers.Serializer):
    plan_slug     = serializers.ChoiceField(choices=["pro", "enterprise"])
    billing_cycle = serializers.ChoiceField(choices=["monthly", "annual"], default="monthly")
    currency      = serializers.CharField(default="NGN")
    card_id       = serializers.UUIDField(required=False, allow_null=True)
    save_card     = serializers.BooleanField(default=False)

    def validate_currency(self, value):
        value = value.upper().strip()
        supported_currencies = {"NGN", "USD", "GHS", "KES", "ZAR"}
        if value not in supported_currencies:
            raise serializers.ValidationError(
                f"Currency '{value}' is not supported. Supported: NGN, USD, GHS, KES, ZAR"
            )
        return value
    


class CompleteSubscriptionSerializer(serializers.Serializer):
    reference = serializers.CharField()
    save_card = serializers.BooleanField(default=False)
    country   = serializers.CharField(default="NG")


class CurrentSubscriptionSerializer(serializers.Serializer):
    """Returned on GET /payments/plans/current/"""
    subscription_id = serializers.UUIDField()
    plan            = serializers.CharField()
    plan_name       = serializers.CharField()
    billing_cycle   = serializers.CharField()
    status          = serializers.CharField()
    amount_paid     = serializers.DecimalField(max_digits=10, decimal_places=2)
    started_at      = serializers.DateTimeField()
    expires_at      = serializers.DateTimeField(allow_null=True)
    days_remaining  = serializers.IntegerField(allow_null=True)