# payments/gateways/paystack.py
import requests
from django.conf import settings
from payments.models import PaymentCard


class PaystackGateway:
    """
    Handles all Paystack interactions.
    Two flows:
      A) initialize_transaction  — creates a Paystack transaction, returns checkout_url + reference
      B) verify_and_charge       — verifies a completed popup transaction, saves card, returns result
      C) charge_saved_card       — charges an existing authorization_code (saved card)
    """

    base_url = "https://api.paystack.co"

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type":  "application/json",
        }

    # ── A: Initialize ─────────────────────────────────────────────────────────

    def initialize_transaction(self, email, amount_kobo, currency, reference, metadata=None):
        """
        Creates a Paystack transaction.
        Returns { reference, checkout_url, amount_kobo }
        """
        payload = {
            "email":     email,
            "amount":    amount_kobo,
            "currency":  currency.upper(),
            "reference": reference,
        }
        if metadata:
            payload["metadata"] = {k: str(v) for k, v in metadata.items()}

        resp = requests.post(
            f"{self.base_url}/transaction/initialize",
            json=payload,
            headers=self.headers,
        ).json()

        self._assert_ok(resp, "Paystack initialize failed")

        return {
            "reference":    reference,
            "checkout_url": resp["data"]["authorization_url"],
            "amount_kobo":  amount_kobo,
        }

    # ── B: Verify popup transaction ───────────────────────────────────────────

    def verify_transaction(self, reference):
        """
        Verifies a completed Paystack popup transaction.
        Returns the full tx data dict.
        Raises on failure.
        """
        resp = requests.get(
            f"{self.base_url}/transaction/verify/{reference}",
            headers=self.headers,
        ).json()

        self._assert_ok(resp, "Paystack verification failed")

        tx = resp["data"]
        if tx.get("status") != "success":
            raise PaystackError(
                f"Transaction not successful (status: {tx.get('status')}, "
                f"gateway: {tx.get('gateway_response')})"
            )
        return tx

    def save_card_from_tx(self, user, tx_data):
        """
        Extracts authorization from a verified tx and saves/returns a PaymentCard.
        Returns (card, is_new).
        """
        card_info = tx_data.get("authorization", {})

        existing = PaymentCard.objects.filter(
            user=user,
            last4=card_info.get("last4", ""),
            exp_month=int(card_info.get("exp_month") or 0),
            exp_year=int(card_info.get("exp_year") or 0),
            brand=card_info.get("card_type", ""),
            provider="paystack",
        ).first()

        if existing:
            if not existing.is_default:
                PaymentCard.objects.filter(user=user).update(is_default=False)
                existing.is_default = True
                existing.save(update_fields=["is_default"])
            return existing, False

        PaymentCard.objects.filter(user=user).update(is_default=False)
        card = PaymentCard.objects.create(
            user=user,
            provider="paystack",
            token=card_info["authorization_code"],
            brand=card_info.get("card_type", ""),
            last4=card_info.get("last4", ""),
            exp_month=int(card_info.get("exp_month") or 0),
            exp_year=int(card_info.get("exp_year") or 0),
            is_default=True,
        )
        return card, True

    # ── C: Charge saved card ──────────────────────────────────────────────────

    def charge_saved_card(self, card, email, amount_kobo, currency):
        """
        Charges a saved card using its authorization_code.
        Returns a PaymentResult.
        """
        resp = requests.post(
            f"{self.base_url}/transaction/charge_authorization",
            json={
                "authorization_code": card.token,
                "email":              email,
                "amount":             amount_kobo,
                "currency":           currency.upper(),
            },
            headers=self.headers,
        ).json()

        self._assert_ok(resp, "Paystack charge failed")

        tx = resp["data"]
        status = self._normalise_status(tx["status"])

        return PaymentResult(
            reference=tx["reference"],
            status=status,
            metadata={
                "reference":        tx["reference"],
                "gateway_response": tx.get("gateway_response"),
                "channel":          tx.get("channel"),
            },
        )

    # ── Customer ──────────────────────────────────────────────────────────────

    def get_or_create_customer(self, user):
        profile = getattr(user, "attendee_profile", None) or getattr(user, "host_profile", None)
        if profile and getattr(profile, "paystack_customer_id", None):
            return profile.paystack_customer_id

        resp = requests.post(
            f"{self.base_url}/customer",
            json={
                "email":      user.email,
                "first_name": user.first_name,
                "last_name":  user.last_name,
            },
            headers=self.headers,
        ).json()
        self._assert_ok(resp, "Failed to create Paystack customer")

        customer_id = resp["data"]["customer_code"]
        if profile:
            profile.paystack_customer_id = customer_id
            profile.save(update_fields=["paystack_customer_id"])
        return customer_id

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_status(s):
        return {"success": "succeeded", "failed": "failed", "pending": "pending"}.get(s, s)

    @staticmethod
    def _assert_ok(resp, message):
        if not resp.get("status"):
            raise PaystackError(f"{message}: {resp.get('message', 'Unknown error')}")


class PaystackError(Exception):
    pass


class PaymentResult:
    def __init__(self, reference, status, metadata=None):
        self.reference = reference
        self.status    = status
        self.metadata  = metadata or {}