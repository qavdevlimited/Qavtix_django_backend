# payments/services/checkout_service.py
import uuid
import logging
from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model

from payments.models import PaymentCard, Payment
from payments.services.factory import get_gateway
from payments.services.paystack_service import PaystackGateway

logger = logging.getLogger(__name__)
User   = get_user_model()


# ─────────────────────────────────────────────────────────────────────────────
# Helper: compute split expiry based on how far away the event is
# ─────────────────────────────────────────────────────────────────────────────

def _split_expiry(event):
    now        = timezone.now()
    days_until = (event.start_datetime - now).days

    if days_until < 2:
        raise CheckoutError(
            "Event is too soon to use split payment (less than 48 hours away).", 400
        )
    elif days_until < 7:
        days = 1
    elif days_until < 30:
        days = 3
    else:
        days = 7

    return now + timezone.timedelta(days=days)


# ─────────────────────────────────────────────────────────────────────────────
# Main CheckoutService
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutService:
    """
    Handles all checkout flows:
      1. Normal single purchase (auth or guest)
      2. Split payment (auth only)
      3. Marketplace purchase (auth only)

    Flow for normal purchase:
      validate → compute totals → initialize Paystack tx → return checkout_url
      (fulfillment happens in CompleteCheckoutService after user pays)

    Flow for split:
      validate → validate split members → compute per-person amounts
      → create SplitOrder + SplitParticipants
      → initiator pays their share immediately (initialize Paystack tx)
      → email others their payment links via Celery

    Flow for marketplace:
      validate listing → reserve it → initialize Paystack tx → return checkout_url
    """

    def __init__(self, user, email, data):
        self.user         = user
        self.email        = email
        self.data         = data
        self.gateway      = get_gateway(data.get("country", "NG"))
        self.full_name    = data.get("full_name", "")
        self.phone_number = data.get("phone_number", "")
        self.is_split     = data.get("is_split", False)
        self.marketplace_listing_id = data.get("marketplace_listing_id")
        self.is_marketplace = bool(self.marketplace_listing_id)

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self):
        if self.is_marketplace:
            return self._handle_marketplace()

        if self.is_split:
            return self._handle_split()

        return self._handle_normal()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Normal purchase
    # ─────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def _handle_normal(self):
        event      = self._get_event()
        line_items = self._validate_tickets(event)
        discount   = self._apply_promo(line_items)
        subtotal   = sum(qty * price for _, qty, price in line_items)
        total      = max(subtotal - discount, Decimal("0.00"))
        reference  = self._generate_reference()

        # Reserve tickets (lock sold_count)
        self._reserve_tickets(line_items)

        # Create pending order
        order = self._create_order(
            event=event,
            line_items=line_items,
            total_amount=total,
            discount=discount,
            reference=reference,
        )

        # Initialize Paystack — get checkout URL
        init = self.gateway.initialize_transaction(
            email=self.email,
            amount_kobo=int(total * 100),
            currency=self.data.get("currency", "NGN"),
            reference=reference,
            metadata={
                "order_id":   str(order.id),
                "full_name":  self.full_name,
                "flow":       "normal",
            },
        )

        return {
            "flow":         "normal",
            "order_id":     str(order.id),
            "reference":    reference,
            "checkout_url": init["checkout_url"],
            "amount":       init["amount_kobo"],
            "currency":     self.data.get("currency", "NGN").upper(),
            "subtotal":     str(subtotal),
            "discount":     str(discount),
            "total":        str(total),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Split payment
    # ─────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def _handle_split(self):
        from transactions.models import SplitOrder, SplitParticipant, IssuedTicket, OrderTicket

        if not self.user:
            raise CheckoutError("Authentication required for split payment.", 401)

        event      = self._get_event()
        line_items = self._validate_tickets(event)
        discount   = self._apply_promo(line_items)
        subtotal   = sum(qty * price for _, qty, price in line_items)
        total      = max(subtotal - discount, Decimal("0.00"))

        split_members = self.data.get("split_members", [])

        # Auto-inject initiator if not already in the list
        initiator_emails = [m["email"] for m in split_members]
        if self.user.email not in initiator_emails:
            # Calculate initiator's percentage as remainder so it always sums to 100
            others_pct = sum(Decimal(str(m["percentage"])) for m in split_members)
            initiator_pct = (Decimal("100") - others_pct).quantize(Decimal("0.01"))

            if initiator_pct <= 0:
                raise CheckoutError(
                    "Split percentages already sum to 100. "
                    "Leave room for your own share or include your email explicitly.", 400
                )

            split_members = [
                {"email": self.user.email, "percentage": initiator_pct},
                *split_members,
            ]
        # split_members = [{ "email": "x@y.com", "percentage": 33.33 }, ...]
        # initiator is always included — their entry should be in the list too

        # Validate total tickets = total participants
        total_tickets = sum(qty for _, qty, _ in line_items)
        if len(split_members) != total_tickets:
            raise CheckoutError(
                f"Number of split members ({len(split_members)}) must equal "
                f"total tickets ({total_tickets}).",
                400,
            )

        # Validate percentages sum to 100
        total_pct = sum(Decimal(str(m["percentage"])) for m in split_members)
        if abs(total_pct - Decimal("100")) > Decimal("0.01"):
            raise CheckoutError(
                f"Split percentages must sum to 100 (got {total_pct}).", 400
            )

        # Validate all members are registered users
        # Also ensure only one ticket type in split
        if len(line_items) > 1:
            raise CheckoutError("Split payment only supports one ticket type per order.", 400)

        member_users = []
        initiator_found = False
        for m in split_members:
            try:
                u = User.objects.get(email=m["email"])
            except User.DoesNotExist:
                raise CheckoutError(
                    f"User with email {m['email']} is not registered. "
                    f"All split members must have a QavTix account.",
                    400,
                )
            if u == self.user:
                initiator_found = True
            member_users.append((u, Decimal(str(m["percentage"]))))

        if not initiator_found:
            raise CheckoutError("Initiator's email must be included in split members.", 400)

        # Compute expiry
        expires_at = _split_expiry(event)

        # Reserve tickets
        self._reserve_tickets(line_items)

        reference = self._generate_reference()

        # Create pending order
        order = self._create_order(
            event=event,
            line_items=line_items,
            total_amount=total,
            discount=discount,
            reference=reference,
        )

        # Create SplitOrder
        split_order = SplitOrder.objects.create(
            order=order,
            initiated_by=self.user,
            total_participants=total_tickets,
            expires_at=expires_at,
        )

        # Create SplitParticipants + reserved IssuedTickets
        ticket, qty, _ = line_items[0]
        order_ticket   = OrderTicket.objects.get(order=order, ticket=ticket)

        participants = []
        initiator_participant = None

        for user_obj, pct in member_users:
            amount = (total * pct / 100).quantize(Decimal("0.01"))

            # Reserve an IssuedTicket for this participant
            issued = IssuedTicket.objects.create(
                order=order,
                order_ticket=order_ticket,
                event=event,
                owner=user_obj,
                original_owner=self.user,
                status="reserved",   # locked until split completes
                metadata={"split": True},
            )

            part = SplitParticipant.objects.create(
                split_order=split_order,
                user=user_obj,
                issued_ticket=issued,
                amount=amount,
                percentage=pct,
            )
            participants.append(part)

            if user_obj == self.user:
                initiator_participant = part

        # Initiator pays immediately — initialize their Paystack transaction
        initiator_amount_kobo = int(initiator_participant.amount * 100)
        init = self.gateway.initialize_transaction(
            email=self.user.email,
            amount_kobo=initiator_amount_kobo,
            currency=self.data.get("currency", "NGN"),
            reference=f"{reference}_init",
            metadata={
                "order_id":        str(order.id),
                "split_order_id":  str(split_order.id),
                "participant_id":  str(initiator_participant.id),
                "flow":            "split_initiator",
            },
        )

        # Queue emails to other participants via Celery
        from payments.tasks import send_split_payment_emails
        other_participants = [p for p in participants if p.user != self.user]
        send_split_payment_emails.delay(
            split_order_id=str(split_order.id),
            participant_ids=[str(p.id) for p in other_participants],
        )

        return {
            "flow":             "split",
            "order_id":         str(order.id),
            "split_order_id":   str(split_order.id),
            "reference":        f"{reference}_init",
            "checkout_url":     init["checkout_url"],
            "amount":           initiator_amount_kobo,
            "currency":         self.data.get("currency", "NGN").upper(),
            "expires_at":       expires_at.isoformat(),
            "total_participants": total_tickets,
            "subtotal":         str(subtotal),
            "discount":         str(discount),
            "total":            str(total),
            "your_share":       str(initiator_participant.amount),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Marketplace purchase
    # ─────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def _handle_marketplace(self):
        from marketplace.models import MarketListing

        if not self.user:
            raise CheckoutError("Authentication required for marketplace purchase.", 401)

        try:
            listing = (
                MarketListing.objects
                .select_for_update()
                .select_related("ticket", "ticket__event", "ticket__order_ticket__ticket", "seller")
                .get(id=self.marketplace_listing_id)
            )
        except MarketListing.DoesNotExist:
            raise CheckoutError("Marketplace listing not found.", 404)

        if listing.status != "active":
            raise CheckoutError("This listing is no longer available.", 400)

        if listing.seller == self.user:
            raise CheckoutError("You cannot purchase your own listing.", 400)

        if listing.expires_at and timezone.now() > listing.expires_at:
            raise CheckoutError("This listing has expired.", 400)

        # Reserve listing
        listing.status = "reserved"
        listing.save(update_fields=["status"])

        event      = listing.ticket.event
        total      = listing.price
        reference  = self._generate_reference()

        # Create pending order (no line_items for marketplace)
        order = self._create_order(
            event=event,
            line_items=None,
            total_amount=total,
            discount=Decimal("0.00"),
            reference=reference,
            marketplace_listing=listing,
        )

        init = self.gateway.initialize_transaction(
            email=self.email,
            amount_kobo=int(total * 100),
            currency=self.data.get("currency", "NGN"),
            reference=reference,
            metadata={
                "order_id":    str(order.id),
                "listing_id":  str(listing.id),
                "flow":        "marketplace",
            },
        )

        return {
            "flow":         "marketplace",
            "order_id":     str(order.id),
            "listing_id":   str(listing.id),
            "reference":    reference,
            "checkout_url": init["checkout_url"],
            "amount":       init["amount_kobo"],
            "currency":     self.data.get("currency", "NGN").upper(),
            "total":        str(total),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Shared helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_event(self):
        from events.models import Event
        try:
            event = Event.objects.select_for_update().get(id=self.data["event_id"])
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
        """
        Increments sold_count to lock inventory during pending payment.
        Called inside atomic block — rolled back if anything fails.
        """
        from events.models import Ticket
        from django.db.models import F
        for ticket, qty, _ in line_items:
            Ticket.objects.filter(id=ticket.id).update(sold_count=F("sold_count") + qty)

    def _create_order(self, event, line_items, total_amount, discount, reference,
                      marketplace_listing=None):
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
            metadata={"reference": reference},
        )

        if line_items:
            for ticket, qty, unit_price in line_items:
                OrderTicket.objects.create(
                    order=order,
                    ticket=ticket,
                    quantity=qty,
                    price=unit_price,
                )
        elif marketplace_listing:
            OrderTicket.objects.create(
                order=order,
                ticket=marketplace_listing.ticket.order_ticket.ticket,
                quantity=1,
                price=marketplace_listing.price,
            )

        return order

    @staticmethod
    def _generate_reference():
        return f"qavtix_{uuid.uuid4().hex[:20]}"


# ─────────────────────────────────────────────────────────────────────────────
# CompleteCheckoutService — called after Paystack popup/redirect completes
# ─────────────────────────────────────────────────────────────────────────────

class CompleteCheckoutService:
    """
    Called when user returns from Paystack with a reference.
    Verifies payment, saves card if requested, issues tickets, completes order.

    Handles all three flows based on metadata in the Paystack transaction.
    """

    def __init__(self, user, email, reference, save_card=False, country="NG"):
        self.user      = user
        self.email     = email
        self.reference = reference
        self.save_card = save_card
        self.gateway   = get_gateway(country)

    @transaction.atomic
    def run(self):
        # 1 — Verify with Paystack
        try:
            tx = self.gateway.verify_transaction(self.reference)
        except Exception as e:
            raise CheckoutError(f"Payment verification failed: {str(e)}", 402)

        metadata = tx.get("metadata") or {}
        flow     = metadata.get("flow", "normal")

        if flow == "normal":
            return self._complete_normal(tx, metadata)
        elif flow == "split_initiator":
            return self._complete_split_initiator(tx, metadata)
        elif flow == "split_participant":
            return self._complete_split_participant(tx, metadata)
        elif flow == "marketplace":
            return self._complete_marketplace(tx, metadata)
        else:
            raise CheckoutError(f"Unknown payment flow: {flow}", 400)

    # ── Normal completion ─────────────────────────────────────────────────────

    def _complete_normal(self, tx, metadata):
        from transactions.models import Order

        order_id = metadata.get("order_id")
        try:
            order = Order.objects.select_for_update().get(id=order_id)
        except Order.DoesNotExist:
            raise CheckoutError("Order not found.", 404)

        if order.status == "completed":
            return {"already_complete": True, "order_id": str(order.id)}

        # Save card
        card = self._maybe_save_card(tx)

        # Persist payment record
        payment = self._persist_payment(
            order=order,
            tx=tx,
            card=card,
        )

        # Issue tickets + complete order
        self._finalise_order(order, payment, card)

        return {
            "flow":     "normal",
            "order_id": str(order.id),
            "status":   "completed",
        }

    # ── Split initiator completion ────────────────────────────────────────────

    def _complete_split_initiator(self, tx, metadata):
        from transactions.models import SplitOrder, SplitParticipant

        participant_id = metadata.get("participant_id")
        try:
            participant = SplitParticipant.objects.select_for_update().select_related(
                "split_order", "split_order__order"
            ).get(id=participant_id)
        except SplitParticipant.DoesNotExist:
            raise CheckoutError("Split participant not found.", 404)

        if participant.status == "paid":
            return {"already_paid": True}

        card = self._maybe_save_card(tx)

        payment = self._persist_payment(
            order=participant.split_order.order,
            tx=tx,
            card=card,
        )

        participant.status            = "paid"
        participant.payment           = payment
        participant.payment_reference = self.reference
        participant.paid_at           = timezone.now()
        participant.save(update_fields=["status", "payment", "payment_reference", "paid_at"])

        split_order = participant.split_order
        split_order.paid_count += 1
        split_order.save(update_fields=["paid_count"])

        completed = split_order.check_completion()
        if completed:
            self._finalise_split(split_order)

        # Send confirmation email to initiator
        from payments.tasks import send_split_initiator_confirmation
        send_split_initiator_confirmation.delay(str(participant.id))

        return {
            "flow":            "split",
            "participant_id":  str(participant.id),
            "split_order_id":  str(split_order.id),
            "paid_count":      split_order.paid_count,
            "total":           split_order.total_participants,
            "split_complete":  completed,
        }

    # ── Split participant (non-initiator) completion ──────────────────────────

    def _complete_split_participant(self, tx, metadata):
        from transactions.models import SplitParticipant

        participant_id = metadata.get("participant_id")
        try:
            participant = SplitParticipant.objects.select_for_update().select_related(
                "split_order", "split_order__order"
            ).get(id=participant_id)
        except SplitParticipant.DoesNotExist:
            raise CheckoutError("Split participant not found.", 404)

        if participant.status == "paid":
            return {"already_paid": True}

        split_order = participant.split_order

        if split_order.is_expired():
            raise CheckoutError("This split payment has expired.", 400)

        card = self._maybe_save_card(tx)

        payment = self._persist_payment(
            order=split_order.order,
            tx=tx,
            card=card,
        )

        participant.status            = "paid"
        participant.payment           = payment
        participant.payment_reference = self.reference
        participant.paid_at           = timezone.now()
        participant.save(update_fields=["status", "payment", "payment_reference", "paid_at"])

        split_order.paid_count += 1
        split_order.save(update_fields=["paid_count"])

        completed = split_order.check_completion()
        if completed:
            self._finalise_split(split_order)

        return {
            "flow":           "split",
            "participant_id": str(participant.id),
            "split_complete": completed,
        }

    # ── Marketplace completion ────────────────────────────────────────────────

    def _complete_marketplace(self, tx, metadata):
        from transactions.models import Order, IssuedTicket
        from marketplace.models import MarketListing

        order_id   = metadata.get("order_id")
        listing_id = metadata.get("listing_id")

        try:
            order   = Order.objects.select_for_update().get(id=order_id)
            listing = MarketListing.objects.select_for_update().select_related(
                "ticket", "ticket__event", "seller"
            ).get(id=listing_id)
        except (Order.DoesNotExist, MarketListing.DoesNotExist):
            raise CheckoutError("Order or listing not found.", 404)

        if order.status == "completed":
            return {"already_complete": True, "order_id": str(order.id)}

        card    = self._maybe_save_card(tx)
        payment = self._persist_payment(order=order, tx=tx, card=card)

        # Transfer ticket ownership
        issued_ticket              = listing.ticket
        issued_ticket.original_owner = issued_ticket.owner   # preserve original
        issued_ticket.owner        = self.user
        issued_ticket.status       = "resold"
        issued_ticket.transferred_at = timezone.now()
        issued_ticket.save(update_fields=["owner", "original_owner", "status", "transferred_at"])

        # Mark listing as sold
        listing.status = "sold"
        listing.save(update_fields=["status"])

        # Complete order
        order.status         = "completed"
        order.payment_method = "paystack"
        order.save(update_fields=["status", "payment_method"])

        return {
            "flow":     "marketplace",
            "order_id": str(order.id),
            "status":   "completed",
        }

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _maybe_save_card(self, tx):
        """Saves card from tx if user is auth and save_card=True. Returns card or None."""
        if self.user and self.save_card:
            card, _ = self.gateway.save_card_from_tx(self.user, tx)
            return card
        return None

    def _persist_payment(self, order, tx, card):
        currency = tx.get("currency", "NGN")
        amount   = Decimal(tx.get("amount", 0)) / 100   # kobo → naira

        return Payment.objects.create(
            user=self.user,
            email=self.email or tx.get("customer", {}).get("email", ""),
            card=card,
            provider="paystack",
            provider_payment_id=tx.get("reference", self.reference),
            amount=amount,
            currency=currency,
            status="succeeded",
            content_type=ContentType.objects.get_for_model(order),
            object_id=order.id,
            metadata={
                "reference":        tx.get("reference"),
                "gateway_response": tx.get("gateway_response"),
                "channel":          tx.get("channel"),
                "paid_at":          tx.get("paid_at"),
            },
        )

    def _finalise_order(self, order, payment, card):
        """Issues tickets and completes a normal order."""
        from transactions.models import IssuedTicket, OrderTicket
        from events.models import Ticket
        from django.db.models import F

        order.status         = "completed"
        order.payment_method = "paystack"
        order.save(update_fields=["status", "payment_method"])

        for order_ticket in order.tickets.select_related("ticket").all():
            for _ in range(order_ticket.quantity):
                IssuedTicket.objects.create(
                    order=order,
                    order_ticket=order_ticket,
                    event=order.event,
                    owner=self.user if self.user else None,
                    guest_email=self.email if not self.user else "",
                    original_owner=self.user if self.user else None,
                    guest_original_email=self.email if not self.user else "",
                    status="active",
                    metadata={},
                )

    def _finalise_split(self, split_order):
        """
        Activates all reserved IssuedTickets and completes the order.
        Called when all split participants have paid.
        """
        from transactions.models import IssuedTicket

        # Activate all reserved tickets
        IssuedTicket.objects.filter(
            order=split_order.order,
            status="reserved",
        ).update(status="active")

        # Complete the order
        order = split_order.order
        order.status         = "completed"
        order.payment_method = "paystack"
        order.save(update_fields=["status", "payment_method"])

        # Notify all participants
        from payments.tasks import send_split_completion_emails
        send_split_completion_emails.delay(str(split_order.id))


# ─────────────────────────────────────────────────────────────────────────────
# SplitExpiry — run periodically via Celery beat to cancel expired splits
# ─────────────────────────────────────────────────────────────────────────────

class SplitExpiryService:
    """
    Called by a periodic Celery task.
    Cancels expired SplitOrders, releases ticket inventory,
    and creates Refund records for participants who already paid.
    """

    @transaction.atomic
    def run(self):
        from transactions.models import SplitOrder, IssuedTicket
        from django.db.models import F

        now     = timezone.now()
        expired = SplitOrder.objects.filter(status="pending", expires_at__lt=now)

        for split_order in expired:
            self._cancel_split(split_order)

    def _cancel_split(self, split_order):
        from transactions.models import SplitOrder, SplitParticipant, IssuedTicket, Refund
        from events.models import Ticket
        from django.db.models import F

        logger.info(f"Cancelling expired split order {split_order.id}")

        # Cancel reserved tickets
        IssuedTicket.objects.filter(
            order=split_order.order, status="reserved"
        ).update(status="cancelled")

        # Release inventory back
        order_tickets = split_order.order.tickets.select_related("ticket").all()
        for ot in order_tickets:
            Ticket.objects.filter(id=ot.ticket.id).update(
                sold_count=F("sold_count") - ot.quantity
            )

        # Refund participants who paid
        paid_participants = split_order.participants.filter(status="paid")
        for participant in paid_participants:
            # Create refund record
            from transactions.models import Refund
            # Avoid duplicate refund records
            if not hasattr(split_order.order, "refund"):
                Refund.objects.get_or_create(
                    order=split_order.order,
                    defaults={
                        "amount": participant.amount,
                        "reason": "cancelled_event",
                        "notes":  f"Split payment expired — participant {participant.user.email}",
                        "status": "pending",
                    },
                )
            participant.status = "refunded"
            participant.save(update_fields=["status"])

            # Notify participant
            from payments.tasks import send_split_refund_notification
            send_split_refund_notification.delay(str(participant.id))

        # Cancel the split and order
        split_order.status = "expired"
        split_order.save(update_fields=["status"])

        split_order.order.status = "cancelled"
        split_order.order.save(update_fields=["status"])


# ─────────────────────────────────────────────────────────────────────────────
# Custom exception
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)