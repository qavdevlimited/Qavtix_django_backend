# payments/services/checkout_service.py
from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from payments.models import PaymentCard, Payment
from payments.services.factory import get_gateway
from marketplace.models import MarketListing
from django.db import transaction
    



class CheckoutService:

    def __init__(self, user, email, data):
        self.user = user
        self.email = email
        self.data = data
        self.gateway = get_gateway(data["country"])
        self.full_name = data.get("full_name", "")
        self.phone_number = data.get("phone_number", "")
        self.is_split = data.get("is_split", False)
        self.marketplace_listing_id = data.get("marketplace_listing_id")
        self.is_marketplace = bool(self.marketplace_listing_id)

    # ------------------------------------------------------------------ #
    # Public entry point                                                   #
    # ------------------------------------------------------------------ #
    def run(self):

        if self.is_marketplace:
            return self._handle_marketplace_checkout()
        
        event = self._get_event()
        line_items = self._validate_tickets(event)
        discount = self._apply_promo(line_items)
        subtotal = sum(qty * price for _, qty, price in line_items)
        total_amount = max(subtotal - discount, Decimal("0.00"))
        card, card_is_temporary = self._resolve_card()
        order = self._create_order(event, line_items, total_amount, discount)
        payment_result = self._charge(card, total_amount)
        payment = self._persist_payment(card, card_is_temporary, order, payment_result, total_amount)
        self._finalise(payment, order, card, line_items)

        

        return {
            "payment": payment,
            "order": order,
            "card": card,
            "card_is_temporary": card_is_temporary,
            "subtotal": subtotal,
            "discount": discount,
            "total_amount": total_amount,
        }

    # ------------------------------------------------------------------ #
    # Steps                                                                #
    # ------------------------------------------------------------------ #
    def _get_event(self):
        from events.models import Event
        try:
            event = Event.objects.select_for_update().get(id=self.data["event_id"])
        except Event.DoesNotExist:
            raise CheckoutError("Event not found", 404)

        if event.status != "active":
            raise CheckoutError(
                f"Event is not available for purchase (status: {event.status})", 400
            )
        return event

    def _validate_tickets(self, event):
        from events.models import Ticket
        now = timezone.now()
        line_items = []

        for item in self.data["tickets"]:
            try:
                ticket = Ticket.objects.select_for_update().get(
                    id=item["ticket_id"], event=event
                )
            except Ticket.DoesNotExist:
                raise CheckoutError(
                    f"Ticket {item['ticket_id']} not found for this event", 404
                )

            qty = item["quantity"]

            if qty > ticket.per_person_max:
                raise CheckoutError(
                    f"Maximum {ticket.per_person_max} ticket(s) of type "
                    f"'{ticket.ticket_type}' allowed per order.",
                    400,
                )

            available = ticket.quantity - ticket.sold_count
            if qty > available:
                raise CheckoutError(
                    f"Only {available} ticket(s) left for '{ticket.ticket_type}'.", 400
                )

            if now < ticket.sales_start or now > ticket.sales_end:
                raise CheckoutError(
                    f"Ticket '{ticket.ticket_type}' is not on sale right now.", 400
                )

            line_items.append((ticket, qty, ticket.price))

        return line_items

    def _apply_promo(self, line_items):
        promo_code_value = self.data.get("promo_code")
        if not promo_code_value:
            return Decimal("0.00")

        now = timezone.now()
        matched_promo = None

        for ticket, _, _ in line_items:
            try:
                matched_promo = ticket.promo_codes.get(
                    code=promo_code_value,
                    valid_till__gte=now.date(),
                )
                break
            except Exception:
                continue

        if not matched_promo:
            raise CheckoutError("Invalid or expired promo code.", 400)

        raw_subtotal = sum(qty * price for _, qty, price in line_items)
        discount = (raw_subtotal * matched_promo.discount_percentage / 100).quantize(
            Decimal("0.01")
        )
        return discount

    def _resolve_card(self):
        """Returns (card, card_is_temporary)."""
        data = self.data
        user = self.user

        if data.get("card_id"):
            if not user:
                raise CheckoutError(
                    "Authentication required to use a saved card", 401
                )
            try:
                card = PaymentCard.objects.get(id=data["card_id"], user=user)
            except PaymentCard.DoesNotExist:
                raise CheckoutError(
                    "Card not found or does not belong to user", 404
                )
            return card, False

        if data.get("payment_method_id"):
            card = self.gateway.add_card(
                user=user,
                payment_method_id=data["payment_method_id"],
                email=self.email,
            )
            if user and data.get("save_card"):
                PaymentCard.objects.filter(user=user).update(is_default=False)
                card.is_default = True
                card.save()
                return card, False
            else:
                card.is_default = False
                return card, True  # temporary — not persisted

        # Default saved card fallback
        if not user:
            raise CheckoutError(
                "Authentication required to use your default card", 401
            )
        card = PaymentCard.objects.filter(user=user, is_default=True).first()
        if not card:
            raise CheckoutError("No default card found", 400)
        return card, False
    

    @transaction.atomic
    def _handle_marketplace_checkout(self):
        try:
            listing = (
                MarketListing.objects
                .select_for_update()
                .select_related(
                    "ticket",
                    "ticket__event",
                    "ticket__order_ticket",
                    "seller"
                )
                .get(id=self.marketplace_listing_id)
            )
        
        except MarketListing.DoesNotExist:
            raise CheckoutError("Marketplace listing not found.", 404)

        # Validate listing
        if listing.status != "active":
            raise CheckoutError("This listing is no longer available.",400)

        if listing.seller == self.user:
            raise CheckoutError("You cannot purchase your own listing.",400)
        
        if self.user and listing.seller_id == self.user.id:
            raise CheckoutError("You cannot buy your own marketplace listing.", 400)
        
        if listing.status != "active":
            raise CheckoutError("This ticket has already been sold.")
        
        listing.status = "reserved"
        listing.save()

    

        event = listing.ticket.event

        subtotal = listing.price
        discount = 0
        total_amount = listing.price

        # Create Order
        order = self._create_order(
            event=event,
            discount=discount,
            total_amount=total_amount,
            marketplace_listing=listing,
        )

        # Create Payment (reuse your existing method)
        card, card_is_temporary = self._resolve_card()
        payment_result = self._charge(card, total_amount)
        payment = self._persist_payment(card, card_is_temporary, order, payment_result, total_amount)
       

        # ⚠️ DO NOT transfer ticket yet
        # Transfer only after payment success callback

        # return {
        #     "order": order,
        #     "payment": payment,
        #     "subtotal": subtotal,
        #     "discount": discount,
        #     "total_amount": total_amount,
        #     "listing": listing,
        # }
    
        return {
            "payment": payment,
            "order": order,
            "card": card,
            "card_is_temporary": card_is_temporary,
            "subtotal": subtotal,
            "discount": discount,
            "total_amount": total_amount,
        }

    def _create_order(self, event=None, line_items=None, total_amount=None, discount=None, marketplace_listing=None):
        from transactions.models import Order, OrderTicket

        order = Order.objects.create(
            user=self.user,
            email=self.email,
            full_name=self.full_name,
            phone_number=self.phone_number,
            is_split=self.is_split,
            event=event,
            total_amount=total_amount,
            discount=discount,
            status="pending",
            marketplace_listing=marketplace_listing,
        )

        # Create OrderTickets only if line_items exist
        if line_items:
            for ticket, qty, unit_price in line_items:
                OrderTicket.objects.create(
                    order=order,
                    ticket=ticket,
                    quantity=qty,
                    price=unit_price,
                )
        # Create OrderTicket for marketplace listing
        elif marketplace_listing:
            OrderTicket.objects.create(
                order=order,
                ticket=marketplace_listing.ticket.order_ticket.ticket,
                quantity=1,
                price=marketplace_listing.price,
            )

        return order

    def _charge(self, card, total_amount):
        return self.gateway.charge_card(
            card=card,
            amount=total_amount,
            currency=self.data["currency"],
            user=self.user,
            email=self.email,
        )
    

    def _persist_payment(self, card, card_is_temporary, order, payment_result, total_amount):
        return Payment.objects.create(
            user=self.user,
            email=self.email,
            card=card if not card_is_temporary else None,
            provider=card.provider,
            provider_payment_id=payment_result.id,
            amount=total_amount,
            currency=self.data["currency"],
            status=payment_result.status,
            content_type=ContentType.objects.get_for_model(order),
            object_id=order.id,
            metadata=payment_result.metadata,
        )

    def _finalise(self, payment, order, card, line_items):
        from events.models import Ticket
        if payment.status == "succeeded":
            order.status = "completed"
            order.payment_method = card.provider
            order.save()

            for ticket, qty, _ in line_items:
                Ticket.objects.filter(id=ticket.id).update(
                    sold_count=ticket.sold_count + qty
                )

        if payment.status == "requires_action":
            return ({
                "payment_id": payment.id,
                "status": payment.status,
                "client_secret": payment.metadata.get("client_secret"),
                "message": "Payment requires authentication"
            })


# ------------------------------------------------------------------ #
# Custom exception carrying an HTTP status code                        #
# ------------------------------------------------------------------ #
class CheckoutError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status
        super().__init__(message)