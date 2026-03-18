# payments/services/card_service.py
from django.db import transaction
from payments.models import PaymentCard


class CardListService:
    """
    Returns all saved cards for a user.
    Single query — no N+1.
    """

    def __init__(self, user):
        self.user = user

    def run(self):
        cards = (
            PaymentCard.objects
            .filter(user=self.user)
            .order_by("-is_default", "-id")
            .values(
                "id", "provider", "brand", "last4",
                "exp_month", "exp_year", "is_default", "created_at"
            )
        )
        return list(cards)


class SetDefaultCardService:
    """
    Sets a card as default and unsets all others.
    Two queries total.
    """

    def __init__(self, user, card_id):
        self.user    = user
        self.card_id = card_id

    @transaction.atomic
    def run(self):
        try:
            card = PaymentCard.objects.get(id=self.card_id, user=self.user)
        except PaymentCard.DoesNotExist:
            raise CardError("Card not found.", 404)

        PaymentCard.objects.filter(user=self.user).update(is_default=False)
        card.is_default = True
        card.save(update_fields=["is_default"])

        return {
            "id":         card.id,
            "brand":      card.brand,
            "last4":      card.last4,
            "is_default": True,
        }


class DeleteCardService:
    """
    Deletes a saved card.
    If it was the default, the next available card becomes default.
    """

    def __init__(self, user, card_id):
        self.user    = user
        self.card_id = card_id

    @transaction.atomic
    def run(self):
        try:
            card = PaymentCard.objects.get(id=self.card_id, user=self.user)
        except PaymentCard.DoesNotExist:
            raise CardError("Card not found.", 404)

        was_default = card.is_default
        card.delete()

        if was_default:
            next_card = PaymentCard.objects.filter(user=self.user).first()
            if next_card:
                next_card.is_default = True
                next_card.save(update_fields=["is_default"])

        return {"deleted": True}


class CardError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)