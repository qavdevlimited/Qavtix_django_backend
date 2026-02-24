# payments/serializers.py
from rest_framework import serializers
from decimal import Decimal
from payments.models import PaymentCard, Payment
from events.models import Ticket


class TicketLineItemSerializer(serializers.Serializer):
    ticket_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class CheckoutPaymentSerializer(serializers.Serializer):
    country = serializers.CharField()
    currency = serializers.CharField(default="USD")
    full_name=serializers.CharField()
    phone_number=serializers.CharField()
    is_split=serializers.BooleanField(default=False)

    # Target is now always an event — Order is created server-side
    event_id = serializers.UUIDField(required=False)
    marketplace_listing_id = serializers.IntegerField(required=False)

    # One or more ticket types with quantities
    tickets = TicketLineItemSerializer(many=True,required=False)

    # Optional promo code applied to the whole order
    promo_code = serializers.CharField(required=False, allow_blank=True)

    # Card: either a saved card id OR a new payment method token
    card_id = serializers.UUIDField(required=False)
    payment_method_id = serializers.CharField(required=False)
    save_card = serializers.BooleanField(default=False)

    # Required for anonymous (unauthenticated) checkout
    email = serializers.EmailField(required=False)


    def validate(self, data):
        # Must supply a payment instrument
        if not data.get("card_id") and not data.get("payment_method_id"):
            raise serializers.ValidationError(
                "Provide either card_id (saved card) or payment_method_id (new card)."
            )
        event_id = data.get("event_id")
        tickets = data.get("tickets")
        marketplace_id = data.get("marketplace_listing_id")

        # Must choose one flow
        if marketplace_id and (event_id or tickets):
            raise serializers.ValidationError(
                "Provide either marketplace_listing_id OR event_id with tickets, not both."
            )

        if not marketplace_id and not (event_id and tickets):
            raise serializers.ValidationError(
                "You must provide either marketplace_listing_id OR event_id with tickets."
            )

        return data


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


class AddCardSerializer(serializers.Serializer):
    payment_method_id = serializers.CharField()
    country = serializers.CharField()
    set_default = serializers.BooleanField(default=False)
