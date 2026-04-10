# payments/services/card_checkout_service.py — UPDATED
# Currency now derived from event host country

import uuid
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from payments.services.factory import get_gateway
from payments.models import PaymentCard, Payment
from payments.services.currency_utils import get_currency_for_event
from payments.services.checkout_service import CheckoutError, _calculate_fees

logger = logging.getLogger(__name__)


class CardCheckoutService:

    def __init__(self, user, data):
        self.user         = user
        self.data         = data
        self.gateway      = get_gateway("NG")   # all currencies use Paystack
        self.email        = user.email
        self.full_name    = data.get("full_name", "")
        self.phone_number = data.get("phone_number", "")

    @transaction.atomic
    def run(self):
        card = self._get_card()

        marketplace_listing_id = self.data.get("marketplace_listing_id")

        if marketplace_listing_id:
            return self._handle_marketplace(card, marketplace_listing_id)

        return self._handle_normal(card)

    def _handle_normal(self, card):
        from transactions.models import Order, OrderTicket, IssuedTicket

        event    = self._get_event()
        currency = get_currency_for_event(event)   # ← derived from host country

        line_items = self._validate_tickets(event)
        discount   = self._apply_promo(line_items)
        subtotal   = sum(qty * price for _, qty, price in line_items)
        base_total = max(subtotal - discount, Decimal("0.00"))
        fees       = _calculate_fees(base_total)
        total      = base_total + fees

        self._reserve_tickets(line_items)

        affiliate_code = str(self.data.get("affiliate_code") or "").strip()
        reference      = self._generate_reference()

        order = Order.objects.create(
            user=self.user,
            email=self.email,
            full_name=self.full_name,
            phone_number=self.phone_number,
            is_split=False,
            event=event,
            total_amount=total,
            discount=discount,
            fees=fees,  
            status="pending",
            metadata={
                "reference":      reference,
                "flow":           "normal",
                "affiliate_code": affiliate_code,
                "card_checkout":  True,
            },
        )

        for ticket, qty, unit_price in line_items:
            OrderTicket.objects.create(
                order=order,
                ticket=ticket,
                quantity=qty,
                price=unit_price,
            )

        result = self.gateway.charge_saved_card(
            card=card,
            email=self.email,
            amount_kobo=int(float(total) * 100),
            currency=currency,
        )

        if result.status != "succeeded":
            raise CheckoutError(
                f"Card charge failed: {result.metadata.get('gateway_response', 'Unknown error')}",
                402,
            )

        payment = Payment.objects.create(
            user=self.user,
            email=self.email,
            card=card,
            provider="paystack",
            provider_payment_id=result.reference,
            amount=total,
            currency=currency,
            status="succeeded",
            content_type=ContentType.objects.get_for_model(order),
            object_id=order.id,
            metadata=result.metadata,
        )

        order.status         = "completed"
        order.payment_method = "paystack"
        order.save(update_fields=["status", "payment_method"])

        for order_ticket in order.tickets.select_related("ticket").all():
            for _ in range(order_ticket.quantity):
                IssuedTicket.objects.create(
                    order=order,
                    order_ticket=order_ticket,
                    event=order.event,
                    owner=self.user,
                    original_owner=self.user,
                    status="active",
                    metadata={},
                )

        self._credit_affiliate(order)

        return {
            "flow":     "card",
            "order_id": str(order.id),
            "status":   "completed",
            "subtotal": str(subtotal),
            "discount": str(discount),
            "total":    str(total),
            "currency": currency,
            "card":     self._card_info(card),
        }

    def _handle_marketplace(self, card, listing_id):
        from marketplace.models import MarketListing
        from transactions.models import Order, OrderTicket
        from attendee.models import AffliateEarnings

        try:
            listing = MarketListing.objects.select_for_update().select_related(
                "ticket__event__host"
            ).get(id=listing_id)
        except MarketListing.DoesNotExist:
            raise CheckoutError("Marketplace listing not found.", 404)

        if listing.status != "active":
            raise CheckoutError("This listing is no longer available.", 400)
        if listing.seller == self.user:
            raise CheckoutError("You cannot purchase your own listing.", 400)
        if listing.expires_at and timezone.now() > listing.expires_at:
            raise CheckoutError("This listing has expired.", 400)

        listing.status = "reserved"
        listing.save(update_fields=["status"])

        event    = listing.ticket.event
        currency = get_currency_for_event(event)   # ← derived from host country
        total    = listing.price
        reference = self._generate_reference()

        order = Order.objects.create(
            user=self.user,
            email=self.email,
            full_name=self.full_name,
            phone_number=self.phone_number,
            is_split=False,
            event=event,
            total_amount=total,
            discount=Decimal("0.00"),
            status="pending",
            marketplace_listing=listing,
            metadata={
                "reference":     reference,
                "flow":          "marketplace",
                "listing_id":    str(listing.id),
                "card_checkout": True,
            },
        )

        result = self.gateway.charge_saved_card(
            card=card,
            email=self.email,
            amount_kobo=int(float(total) * 100),
            currency=currency,
        )

        if result.status != "succeeded":
            raise CheckoutError(
                f"Card charge failed: {result.metadata.get('gateway_response', 'Unknown error')}",
                402,
            )

        payment = Payment.objects.create(
            user=self.user,
            email=self.email,
            card=card,
            provider="paystack",
            provider_payment_id=result.reference,
            amount=total,
            currency=currency,
            status="succeeded",
            content_type=ContentType.objects.get_for_model(order),
            object_id=order.id,
            metadata=result.metadata,
        )

        issued_ticket                = listing.ticket
        issued_ticket.original_owner = issued_ticket.owner
        issued_ticket.owner          = self.user
        issued_ticket.status         = "resold"
        issued_ticket.transferred_at = timezone.now()
        issued_ticket.save(update_fields=["owner", "original_owner", "status", "transferred_at"])

        listing.status = "sold"
        listing.save(update_fields=["status"])

        order.status         = "completed"
        order.payment_method = "paystack"
        order.save(update_fields=["status", "payment_method"])

        seller_attendee = listing.seller.attendee_profile
        AffliateEarnings.objects.get_or_create(
            attendee          = seller_attendee,
            marketplace_order = order,
            earning_type      = "marketplace",
            defaults={
                "earning": listing.price,
                "status":  "pending",
            },
        )

        return {
            "flow":       "card_marketplace",
            "order_id":   str(order.id),
            "listing_id": str(listing.id),
            "status":     "completed",
            "total":      str(total),
            "currency":   currency,
            "card":       self._card_info(card),
        }

    def _get_card(self):
        card_id = self.data.get("card_id")
        if not card_id:
            raise CheckoutError("card_id is required.", 400)
        try:
            return PaymentCard.objects.get(id=card_id, user=self.user)
        except PaymentCard.DoesNotExist:
            raise CheckoutError("Card not found.", 404)

    def _get_event(self):
        from events.models import Event
        try:
            event = Event.objects.select_for_update().select_related("host").get(
                id=self.data["event_id"]
            )
        except Event.DoesNotExist:
            raise CheckoutError("Event not found.", 404)
        if event.status != "active":
            raise CheckoutError(f"Event is not available for purchase (status: {event.status}).", 400)
        if event.end_datetime < timezone.now():
            raise CheckoutError("This event has already ended.", 400)
        return event

    def _validate_tickets(self, event):
        from events.models import Ticket
        now        = timezone.now()
        line_items = []
        for item in self.data["tickets"]:
            try:
                ticket = Ticket.objects.select_for_update().get(id=item["ticket_id"], event=event)
            except Ticket.DoesNotExist:
                raise CheckoutError(f"Ticket {item['ticket_id']} not found for this event.", 404)

            qty       = item["quantity"]
            available = ticket.quantity - ticket.sold_count

            if qty > ticket.per_person_max:
                raise CheckoutError(
                    f"Maximum {ticket.per_person_max} ticket(s) of type '{ticket.ticket_type}' per order.", 400
                )
            if qty > available:
                raise CheckoutError(f"Only {available} ticket(s) left for '{ticket.ticket_type}'.", 400)
            if now < ticket.sales_start or now > ticket.sales_end:
                raise CheckoutError(f"Ticket '{ticket.ticket_type}' is not on sale right now.", 400)

            line_items.append((ticket, qty, ticket.price))
        return line_items

    def _apply_promo(self, line_items):
        promo_code = self.data.get("promo_code", "").strip()
        if not promo_code:
            return Decimal("0.00")

        now     = timezone.now()
        matched = None
        for ticket, _, _ in line_items:
            try:
                matched = ticket.promo_codes.get(code=promo_code, valid_till__gte=now.date())
                break
            except Exception:
                continue

        if not matched:
            raise CheckoutError("Invalid or expired promo code.", 400)

        raw      = sum(qty * price for _, qty, price in line_items)
        discount = (raw * matched.discount_percentage / 100).quantize(Decimal("0.01"))
        return discount

    def _reserve_tickets(self, line_items):
        from events.models import Ticket
        from django.db.models import F
        for ticket, qty, _ in line_items:
            Ticket.objects.filter(id=ticket.id).update(sold_count=F("sold_count") + qty)

    def _credit_affiliate(self, order):
        from attendee.models import AffiliateLink, AffliateEarnings
        from django.db.models import F

        affiliate_code = order.metadata.get("affiliate_code", "").strip()
        if not affiliate_code:
            return

        try:
            link = AffiliateLink.objects.select_related(
                "user__attendee_profile"
            ).get(code=affiliate_code, event=order.event)
        except (AffiliateLink.DoesNotExist, Exception):
            return

        event = order.event
        if not event.affiliate_enabled:
            return

        now = timezone.now()
        if event.affiliate_start and now < event.affiliate_start:
            return
        if event.affiliate_end and now > event.affiliate_end:
            return

        commission_pct = Decimal(str(event.commission_percentage or 0))
        if commission_pct <= 0:
            return

        earning_amount = (order.total_amount * commission_pct / 100).quantize(Decimal("0.01"))

        _, created = AffliateEarnings.objects.get_or_create(
            marketplace_order = order,
            earning_type      = "affiliate",
            defaults={
                "link":     link,
                "attendee": link.user.attendee_profile,
                "earning":  earning_amount,
                "status":   "pending",
            },
        )

        if created:
            AffiliateLink.objects.filter(id=link.id).update(sales=F("sales") + 1)

    @staticmethod
    def _card_info(card):
        return {
            "id":        card.id,
            "brand":     card.brand,
            "last4":     card.last4,
            "exp_month": card.exp_month,
            "exp_year":  card.exp_year,
        }

    @staticmethod
    def _generate_reference():
        return f"qavtix_{uuid.uuid4().hex[:20]}"