# payments/services/checkout_service.py — COMPLETE UPDATED FILE
import uuid
import logging
from decimal import Decimal
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model

from attendee.models import AffliateEarnings
from payments.models import PaymentCard, Payment
from payments.services.factory import get_gateway
from payments.services.currency_utils import get_currency_for_event, get_gateway_country_code
from transactions.models import SplitParticipant
from datetime import date

logger = logging.getLogger(__name__)
User   = get_user_model()


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


class CheckoutService:
    """
    Handles all checkout flows.
    Currency is now always derived from the event's host country — never from FE input.
    """

    def __init__(self, user, email, data):
        self.user         = user
        self.email        = email
        self.data         = data
        self.gateway      = get_gateway("NG")   # all currencies use Paystack for now
        self.full_name    = data.get("full_name", "")
        self.phone_number = data.get("phone_number", "")
        self.is_split     = data.get("is_split", False)
        self.marketplace_listing_id = data.get("marketplace_listing_id")
        self.is_marketplace = bool(self.marketplace_listing_id)

    def run(self):
        if self.is_marketplace:
            return self._handle_marketplace()
        if self.is_split:
            return self._handle_split()
        return self._handle_normal()

    # ── Normal purchase ───────────────────────────────────────────────────────

    @transaction.atomic
    def _handle_normal(self):
        event      = self._get_event()
        currency   = get_currency_for_event(event)   # ← derived from host country
        line_items = self._validate_tickets(event)
        discount   = self._apply_promo(line_items)
        subtotal   = sum(qty * price for _, qty, price in line_items)
        total      = max(subtotal - discount, Decimal("0.00"))
        reference  = self._generate_reference()

        self._reserve_tickets(line_items)

        order = self._create_order(
            event=event,
            line_items=line_items,
            total_amount=total,
            discount=discount,
            metadata={
                "reference":      reference,
                "flow":           "normal",
                "affiliate_code": str(self.data.get("affiliate_code") or "").strip(),
            },
        )

        init = self.gateway.initialize_transaction(
            email=self.email,
            amount_kobo=int(total * 100),
            currency=currency,
            reference=reference,
        )

        return {
            "flow":         "normal",
            "order_id":     str(order.id),
            "reference":    reference,
            "checkout_url": init["checkout_url"],
            "amount":       init["amount_kobo"],
            "currency":     currency,
            "subtotal":     str(subtotal),
            "discount":     str(discount),
            "total":        str(total),
        }

    # ── Split payment ─────────────────────────────────────────────────────────

    @transaction.atomic
    def _handle_split(self):
        from transactions.models import SplitOrder, SplitParticipant, IssuedTicket, OrderTicket

        if not self.user:
            raise CheckoutError("Authentication required for split payment.", 401)

        event      = self._get_event()

        if event.age_restriction:
            # 1. Initiator (the logged-in user who started the split)
            initiator_dob = self.data.get("date_of_birth")
            if not initiator_dob:
                raise CheckoutError(
                    "This event requires your date of birth (as the initiator).", 400
                )

            today = date.today()
            initiator_age = (
                today.year - initiator_dob.year -
                ((today.month, today.day) < (initiator_dob.month, initiator_dob.day))
            )
            if initiator_age < 18:
                raise CheckoutError(
                    "You (as initiator) must be 18+ to purchase tickets for this event.", 400
                )

            # 2. Every other split member (the ones sent in the request)
            split_members = self.data.get("split_members", [])
            for member in split_members:
                member_dob = member.get("date_of_birth")
                if not member_dob:
                    raise CheckoutError(
                        f"Date of birth is required for split member with email {member.get('email')}. "
                        "This event has age restriction.", 400
                    )

                member_age = (
                    today.year - member_dob.year -
                    ((today.month, today.day) < (member_dob.month, member_dob.day))
                )
                if member_age < 18:
                    raise CheckoutError(
                        f"The user with email {member.get('email')} does not meet the age requirement "
                        "(must be 18+) for this event.", 400
                    )
                
        currency   = get_currency_for_event(event)   # ← derived from host country
        line_items = self._validate_tickets(event)
        discount   = self._apply_promo(line_items)
        subtotal   = sum(qty * price for _, qty, price in line_items)
        total      = max(subtotal - discount, Decimal("0.00"))

        if len(line_items) > 1:
            raise CheckoutError("Split payment only supports one ticket type per order.", 400)

        split_members = list(self.data.get("split_members", []))

        initiator_emails = [m["email"] for m in split_members]
        if self.user.email not in initiator_emails:
            others_pct    = sum(Decimal(str(m["percentage"])) for m in split_members)
            initiator_pct = (Decimal("100") - others_pct).quantize(Decimal("0.01"))
            if initiator_pct <= 0:
                raise CheckoutError(
                    "Split percentages already sum to 100. Leave room for your own share.", 400
                )
            split_members = [
                {"email": self.user.email, "percentage": str(initiator_pct)},
                *split_members,
            ]

        total_tickets = sum(qty for _, qty, _ in line_items)
        if len(split_members) != total_tickets:
            raise CheckoutError(
                f"Number of split members ({len(split_members)}) must equal "
                f"total tickets ({total_tickets}).",
                400,
            )

        total_pct = sum(Decimal(str(m["percentage"])) for m in split_members)
        if abs(total_pct - Decimal("100")) > Decimal("0.01"):
            raise CheckoutError(
                f"Split percentages must sum to 100 (got {total_pct}).", 400
            )

        member_users    = []
        initiator_found = False
        for m in split_members:
            try:
                u = User.objects.get(email=m["email"])
            except User.DoesNotExist:
                raise CheckoutError(
                    f"User with email {m['email']} is not registered.",
                    400,
                )
            if u.email == self.user.email:
                initiator_found = True
            member_users.append((u, Decimal(str(m["percentage"]))))

        if not initiator_found:
            raise CheckoutError("Could not resolve initiator in split members.", 400)

        expires_at = _split_expiry(event)
        reference  = self._generate_reference()

        self._reserve_tickets(line_items)

        order = self._create_order(
            event=event,
            line_items=line_items,
            total_amount=total,
            discount=discount,
            metadata={
                "reference": reference,
                "flow":      "split",
            },
        )

        split_order = SplitOrder.objects.create(
            order=order,
            initiated_by=self.user,
            total_participants=total_tickets,
            expires_at=expires_at,
        )

        order.metadata["split_order_id"] = str(split_order.id)
        order.save(update_fields=["metadata"])

        ticket, qty, _ = line_items[0]
        order_ticket   = OrderTicket.objects.get(order=order, ticket=ticket)

        participants          = []
        initiator_participant = None

        for user_obj, pct in member_users:
            amount = (total * pct / 100).quantize(Decimal("0.01"))

            issued = IssuedTicket.objects.create(
                order=order,
                order_ticket=order_ticket,
                event=event,
                owner=user_obj,
                original_owner=self.user,
                status="reserved",
                metadata={"split": True},
            )

            part = SplitParticipant.objects.create(
                split_order=split_order,
                user=user_obj,
                issued_ticket=issued,
                amount=amount,
                percentage=float(pct),
            )
            participants.append(part)

            if user_obj.email == self.user.email:
                initiator_participant = part

        if initiator_participant is None:
            raise CheckoutError("Could not find initiator participant record.", 400)

        initiator_reference = f"{reference}_init"
        initiator_participant.payment_reference = initiator_reference
        initiator_participant.save(update_fields=["payment_reference"])

        initiator_amount_kobo = int(float(initiator_participant.amount) * 100)
        init = self.gateway.initialize_transaction(
            email=self.user.email,
            amount_kobo=initiator_amount_kobo,
            currency=currency,
            reference=initiator_reference,
        )

        other_participants = [p for p in participants if p.user.email != self.user.email]
        from payments.tasks import send_split_payment_emails
        send_split_payment_emails.delay(
            split_order_id=str(split_order.id),
            participant_ids=[str(p.id) for p in other_participants],
        )

        return {
            "flow":               "split",
            "order_id":           str(order.id),
            "split_order_id":     str(split_order.id),
            "reference":          initiator_reference,
            "checkout_url":       init["checkout_url"],
            "amount":             initiator_amount_kobo,
            "currency":           currency,
            "expires_at":         expires_at.isoformat(),
            "total_participants": total_tickets,
            "subtotal":           str(subtotal),
            "discount":           str(discount),
            "total":              str(total),
            "your_share":         str(initiator_participant.amount),
        }

    # ── Marketplace purchase ──────────────────────────────────────────────────

    @transaction.atomic
    def _handle_marketplace(self):
        from marketplace.models import MarketListing

        if not self.user:
            raise CheckoutError("Authentication required for marketplace purchase.", 401)

        try:
            listing = (
                MarketListing.objects
                .select_for_update()
                .select_related("ticket", "ticket__event", "ticket__event__host", "seller")
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

        listing.status = "reserved"
        listing.save(update_fields=["status"])

        event    = listing.ticket.event
        currency = get_currency_for_event(event)   # ← derived from host country
        total    = listing.price
        reference = self._generate_reference()

        order = self._create_order(
            event=event,
            line_items=None,
            total_amount=total,
            discount=Decimal("0.00"),
            metadata={
                "reference":  reference,
                "flow":       "marketplace",
                "listing_id": str(listing.id),
            },
            marketplace_listing=listing,
        )

        init = self.gateway.initialize_transaction(
            email=self.email,
            amount_kobo=int(total * 100),
            currency=currency,
            reference=reference,
        )

        return {
            "flow":         "marketplace",
            "order_id":     str(order.id),
            "listing_id":   str(listing.id),
            "reference":    reference,
            "checkout_url": init["checkout_url"],
            "amount":       init["amount_kobo"],
            "currency":     currency,
            "total":        str(total),
        }

    # ── Shared helpers ────────────────────────────────────────────────────────

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

    def _create_order(self, event, line_items, total_amount, discount, metadata,
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
            metadata=metadata,
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
# CompleteCheckoutService
# ─────────────────────────────────────────────────────────────────────────────

class CompleteCheckoutService:

    def __init__(self, user, email, reference, save_card=False, country="NG"):
        self.user      = user
        self.email     = email
        self.reference = reference
        self.save_card = save_card
        self.gateway   = get_gateway("NG")  # all currencies use Paystack

    @transaction.atomic
    def run(self):
        try:
            tx = self.gateway.verify_transaction(self.reference)
        except Exception as e:
            raise CheckoutError(f"Payment verification failed: {str(e)}", 402)

        try:
            participant = SplitParticipant.objects.select_for_update().select_related(
                "split_order__order"
            ).get(payment_reference=self.reference)
            return self._complete_split_participant(tx, participant)
        except SplitParticipant.DoesNotExist:
            pass

        order, flow, participant = self._find_order_and_flow()

        if flow == "normal":
            return self._complete_normal(tx, order)
        elif flow == "split":
            return self._complete_split_initiator(tx, order)
        elif flow == "split_participant":
            return self._complete_split_participant(tx, participant)
        elif flow == "marketplace":
            return self._complete_marketplace(tx, order)
        else:
            raise CheckoutError(f"Unknown payment flow: {flow}", 400)

    def _find_order_and_flow(self):
        from transactions.models import Order, SplitParticipant

        try:
            order = Order.objects.select_for_update().get(
                metadata__reference=self.reference
            )
            return order, order.metadata.get("flow", "normal"), None
        except Order.DoesNotExist:
            pass

        if self.reference.endswith("_init"):
            base_ref = self.reference[:-5]
            try:
                order = Order.objects.select_for_update().get(
                    metadata__reference=base_ref
                )
                return order, "split", None
            except Order.DoesNotExist:
                pass

        try:
            participant = SplitParticipant.objects.select_for_update().select_related(
                "split_order__order"
            ).get(payment_reference=self.reference)
            return participant.split_order.order, "split_participant", participant
        except SplitParticipant.DoesNotExist:
            pass

        raise CheckoutError("Order not found for this reference.", 404)

    def _complete_normal(self, tx, order):
        if order.status == "completed":
            return {"already_complete": True, "order_id": str(order.id)}

        card    = self._maybe_save_card(tx)
        payment = self._persist_payment(order=order, tx=tx, card=card)
        self._finalise_order(order, payment, card)

        return {
            "flow":     "normal",
            "order_id": str(order.id),
            "status":   "completed",
        }

    def _complete_split_initiator(self, tx, order):
        from transactions.models import SplitParticipant

        split_order = order.split_order

        try:
            participant = split_order.participants.select_for_update().get(
                user__email=self.user.email if self.user else ""
            )
        except SplitParticipant.DoesNotExist:
            raise CheckoutError("Initiator participant record not found.", 404)

        if participant.status == "paid":
            return {"already_paid": True}

        card    = self._maybe_save_card(tx)
        payment = self._persist_payment(order=order, tx=tx, card=card)

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

        from payments.tasks import send_split_initiator_confirmation
        send_split_initiator_confirmation.delay(str(participant.id))

        return {
            "flow":           "split",
            "split_order_id": str(split_order.id),
            "paid_count":     split_order.paid_count,
            "total":          split_order.total_participants,
            "split_complete": completed,
        }

    def _complete_split_participant(self, tx, participant):
        split_order = participant.split_order

        if participant.status == "paid":
            return {"already_paid": True}

        if split_order.is_expired():
            raise CheckoutError("This split payment has expired.", 400)

        card    = self._maybe_save_card(tx)
        payment = self._persist_payment(order=split_order.order, tx=tx, card=card)

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
            "flow":           "split_participant",
            "participant_id": str(participant.id),
            "split_complete": completed,
        }

    def _complete_marketplace(self, tx, order):
        from marketplace.models import MarketListing
        from attendee.models import AffliateEarnings

        if order.status == "completed":
            return {"already_complete": True, "order_id": str(order.id)}

        listing_id = order.metadata.get("listing_id")
        try:
            listing = MarketListing.objects.select_for_update().get(id=listing_id)
        except MarketListing.DoesNotExist:
            raise CheckoutError("Marketplace listing not found.", 404)

        if listing.status == "sold":
            return {"already_complete": True, "order_id": str(order.id)}

        issued_ticket   = listing.ticket
        seller          = listing.seller
        seller_attendee = seller.attendee_profile

        card    = self._maybe_save_card(tx)
        payment = self._persist_payment(order=order, tx=tx, card=card)

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
            "flow":     "marketplace",
            "order_id": str(order.id),
            "status":   "completed",
        }

    def _maybe_save_card(self, tx):
        if self.user and self.save_card:
            card, _ = self.gateway.save_card_from_tx(self.user, tx)
            return card
        return None

    def _persist_payment(self, order, tx, card):
        currency = tx.get("currency", "NGN")
        amount   = Decimal(str(tx.get("amount", 0))) / 100

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
        from transactions.models import IssuedTicket

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
        self._credit_affiliate(order)

    def _finalise_split(self, split_order):
        from transactions.models import IssuedTicket

        IssuedTicket.objects.filter(
            order=split_order.order,
            status="reserved",
        ).update(status="active")

        order                = split_order.order
        order.status         = "completed"
        order.payment_method = "paystack"
        order.save(update_fields=["status", "payment_method"])

        from payments.tasks import send_split_completion_emails
        send_split_completion_emails.delay(str(split_order.id))

    def _credit_affiliate(self, order):
        from attendee.models import AffiliateLink
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


# ─────────────────────────────────────────────────────────────────────────────
# SplitExpiryService
# ─────────────────────────────────────────────────────────────────────────────

class SplitExpiryService:

    @transaction.atomic
    def run(self):
        from transactions.models import SplitOrder

        expired = SplitOrder.objects.filter(
            status="pending",
            expires_at__lt=timezone.now()
        )
        for split_order in expired:
            self._cancel_split(split_order)

    def _cancel_split(self, split_order):
        from transactions.models import IssuedTicket, Refund
        from events.models import Ticket
        from django.db.models import F

        logger.info(f"Cancelling expired split order {split_order.id}")

        IssuedTicket.objects.filter(
            order=split_order.order, status="reserved"
        ).update(status="cancelled")

        for ot in split_order.order.tickets.select_related("ticket").all():
            Ticket.objects.filter(id=ot.ticket.id).update(
                sold_count=F("sold_count") - ot.quantity
            )

        for participant in split_order.participants.filter(status="paid"):
            Refund.objects.get_or_create(
                order=split_order.order,
                defaults={
                    "amount": participant.amount,
                    "reason": "cancelled_event",
                    "notes":  f"Split expired — {participant.user.email}",
                    "status": "pending",
                },
            )
            participant.status = "refunded"
            participant.save(update_fields=["status"])

            from payments.tasks import send_split_refund_notification
            send_split_refund_notification.delay(str(participant.id))

        split_order.status = "expired"
        split_order.save(update_fields=["status"])

        split_order.order.status = "cancelled"
        split_order.order.save(update_fields=["status"])


class CheckoutError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)