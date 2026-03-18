# payments/services/add_card_service.py
import uuid
import requests
import logging
from django.conf import settings
from django.db import transaction

from payments.services.factory import get_gateway

logger = logging.getLogger(__name__)

VERIFICATION_AMOUNT_KOBO = 5000  # ₦50


class AddCardInitiateService:
    """
    Step 1 — Initialize a small Paystack charge to capture card details.
    Returns checkout_url for FE to open in Paystack popup.
    """

    def __init__(self, user, country="NG", currency="NGN"):
        self.user     = user
        self.country  = country
        self.currency = currency
        self.gateway  = get_gateway(country)

    def run(self):
        reference = f"qavtix_addcard_{uuid.uuid4().hex[:16]}"

        init = self.gateway.initialize_transaction(
            email=self.user.email,
            amount_kobo=VERIFICATION_AMOUNT_KOBO,
            currency=self.currency,
            reference=reference,
        )

        return {
            "reference":    reference,
            "checkout_url": init["checkout_url"],
            "amount":       VERIFICATION_AMOUNT_KOBO,
            "currency":     self.currency.upper(),
            "message":      "Complete payment to add your card. ₦50 will be refunded.",
        }


class AddCardConfirmService:
    """
    Step 2 — Verify the transaction, save the card, refund the ₦50 charge.
    """

    def __init__(self, user, reference, country="NG", set_default=True):
        self.user        = user
        self.reference   = reference
        self.country     = country
        self.set_default = set_default
        self.gateway     = get_gateway(country)

    @transaction.atomic
    def run(self):
        tx = self.gateway.verify_transaction(self.reference)

        card, is_new = self.gateway.save_card_from_tx(self.user, tx)

        try:
            self._refund(self.reference, VERIFICATION_AMOUNT_KOBO)
        except Exception as e:
            logger.error(
                f"Failed to refund card verification charge. "
                f"Reference: {self.reference}, User: {self.user.id}, Error: {e}"
            )

        return {
            "id":         card.id,
            "provider":   card.provider,
            "brand":      card.brand,
            "last4":      card.last4,
            "exp_month":  card.exp_month,
            "exp_year":   card.exp_year,
            "is_default": card.is_default,
            "is_new":     is_new,
        }

    def _refund(self, reference, amount_kobo):
        resp = requests.post(
            "https://api.paystack.co/refund",
            json={
                "transaction": reference,
                "amount":      amount_kobo,
            },
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type":  "application/json",
            },
        ).json()

        if not resp.get("status"):
            raise Exception(f"Paystack refund failed: {resp.get('message')}")

        logger.info(f"Refund issued for card verification. Reference: {reference}")