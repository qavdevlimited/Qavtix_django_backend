# payments/serializers.py
from rest_framework import serializers
from decimal import Decimal
from payments.models import PaymentCard, Payment
from events.models import Ticket


class TicketLineItemSerializer(serializers.Serializer):
    ticket_id = serializers.IntegerField()
    quantity  = serializers.IntegerField(min_value=1)


class SplitMemberSerializer(serializers.Serializer):
    email      = serializers.EmailField()
    percentage = serializers.DecimalField(max_digits=5, decimal_places=2)


class CheckoutSerializer(serializers.Serializer):
    # Location — determines gateway
    country  = serializers.CharField(default="NG")
    currency = serializers.CharField(default="NGN")

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
 