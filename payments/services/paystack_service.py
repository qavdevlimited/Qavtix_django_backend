import requests
from django.conf import settings
from payments.models import PaymentCard, Payment
from .base import PaymentGateway


class PaystackGateway(PaymentGateway):

    base_url = "https://api.paystack.co"

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

    def create_customer(self, user=None, email=None):
        """
        Returns a Paystack customer ID.
        - Authenticated users: create once and cache on user.paystack_customer_id
        - Guests: create a one-off customer using their email (not cached)
        """
        if user is not None:
            if hasattr(user, "paystack_customer_id") and user.paystack_customer_id:
                return user.paystack_customer_id

            data = {
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
            }
            resp = requests.post(
                f"{self.base_url}/customer", json=data, headers=self.headers
            ).json()

            self._assert_ok(resp, "Failed to create Paystack customer")

            customer_id = resp["data"]["customer_code"]
            user.paystack_customer_id = customer_id
            user.save(update_fields=["paystack_customer_id"])
            return customer_id

        # Guest checkout — ephemeral customer, not saved anywhere
        if not email:
            raise ValueError("Either a user or an email is required to create a Paystack customer.")

        data = {"email": email}
        resp = requests.post(
            f"{self.base_url}/customer", json=data, headers=self.headers
        ).json()

        self._assert_ok(resp, "Failed to create Paystack guest customer")
        return resp["data"]["customer_code"]

    def add_card(self, user=None, authorization_code=None, email=None):
        """
        Verifies a Paystack transaction and extracts card details.
        - Authenticated users: card is returned unsaved (view handles persistence).
        - Guests: card object is built in memory only (not saved).

        NOTE: `authorization_code` here is actually the transaction REFERENCE
        returned by Paystack's frontend after the user pays. We verify it to
        extract the reusable authorization_code for future charges.
        """
        resp = requests.get(
            f"{self.base_url}/transaction/verify/{authorization_code}",
            headers=self.headers,
        ).json()

        self._assert_ok(resp, "Failed to verify Paystack transaction")

        card_info = resp["data"]["authorization"]

        card = PaymentCard(
            user=user,           # None for guests — view will not save it
            provider="paystack",
            token=card_info["authorization_code"],
            brand=card_info.get("card_type", ""),
            last4=card_info.get("last4", ""),
            exp_month=int(card_info.get("exp_month") or 0),
            exp_year=int(card_info.get("exp_year") or 0),
            is_default=False,    # view controls is_default
        )
        return card

    def charge_card(self, card: PaymentCard, amount, currency="NGN", user=None, email=None):
        """
        Charges a card via Paystack charge_authorization.
        - Resolves email from authenticated user or guest email param.
        - Returns a lightweight result object — view handles Payment persistence.
        """
        charge_email = user.email if user is not None else email
        if not charge_email:
            raise ValueError("An email is required to charge via Paystack.")

        data = {
            "authorization_code": card.token,
            "email": charge_email,
            "amount": int(amount * 100),    # Paystack works in kobo
            "currency": currency.upper(),
        }

        resp = requests.post(
            f"{self.base_url}/transaction/charge_authorization",
            json=data,
            headers=self.headers,
        ).json()

        self._assert_ok(resp, "Paystack charge failed")

        tx = resp["data"]
        return _PaymentResult(
            id=tx["reference"],
            status=tx["status"],
            metadata={
                "reference": tx["reference"],
                "gateway_response": tx.get("gateway_response"),
                "channel": tx.get("channel"),
            },
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _assert_ok(resp, message="Paystack error"):
        if not resp.get("status"):
            raise Exception(f"{message}: {resp.get('message', 'Unknown error')}")
        

class _PaymentResult:
    def __init__(self, id, status, metadata=None):
        self.id = id
        self.status = status
        self.metadata = metadata or {}