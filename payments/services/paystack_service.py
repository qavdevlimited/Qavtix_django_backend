# payments/services/paystack_intent.py
import uuid
import requests
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from events.models import Event, Ticket


class PaystackIntentService:
    base_url = "https://api.paystack.co"

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
        }

    def __init__(self, user, email, data):
        self.user  = user
        self.email = email
        self.data  = data

    def run(self):
        event      = self._get_event()
        line_items = self._validate_tickets(event)
        discount   = self._apply_promo(line_items)
        subtotal   = sum(qty * price for _, qty, price in line_items)
        total      = max(subtotal - discount, Decimal("0.00"))
        reference  = f"qavtix_{uuid.uuid4().hex[:16]}"

        resp = requests.post(
            f"{self.base_url}/transaction/initialize",
            json={
                "email":     self.email,
                "amount":    int(total * 100),   # kobo
                "currency":  self.data.get("currency", "NGN").upper(),
                "reference": reference,
            },
            headers=self.headers,
        ).json()

        if not resp.get("status"):
            raise Exception(f"Paystack init failed: {resp.get('message')}")

        return {
            "amount":    int(total * 100),
            "currency":  self.data.get("currency", "NGN").upper(),
            "email":     self.email,
            "reference": reference,
            "subtotal":  str(subtotal),
            "discount":  str(discount),
            "total":     str(total),
        }

    def _get_event(self):
        try:
            return Event.objects.get(id=self.data["event_id"])
        except Event.DoesNotExist:
            raise Exception("Event not found")

    def _validate_tickets(self, event):
        now        = timezone.now()
        line_items = []
        for item in self.data["tickets"]:
            try:
                ticket = Ticket.objects.get(id=item["ticket_id"], event=event)
            except Ticket.DoesNotExist:
                raise Exception(f"Ticket {item['ticket_id']} not found")

            qty       = item["quantity"]
            available = ticket.quantity - ticket.sold_count

            if qty > ticket.per_person_max:
                raise Exception(f"Max {ticket.per_person_max} tickets allowed per order")
            if qty > available:
                raise Exception(f"Only {available} tickets left")
            if now < ticket.sales_start or now > ticket.sales_end:
                raise Exception(f"Ticket '{ticket.ticket_type}' is not on sale right now")

            line_items.append((ticket, qty, ticket.price))
        return line_items

    def _apply_promo(self, line_items):
        promo_code = self.data.get("promo_code")
        if not promo_code:
            return Decimal("0.00")

        now          = timezone.now()
        matched      = None
        for ticket, _, _ in line_items:
            try:
                matched = ticket.promo_codes.get(
                    code=promo_code, valid_till__gte=now.date()
                )
                break
            except Exception:
                continue

        if not matched:
            raise Exception("Invalid or expired promo code")

        raw = sum(qty * price for _, qty, price in line_items)
        return (raw * matched.discount_percentage / 100).quantize(Decimal("0.01"))