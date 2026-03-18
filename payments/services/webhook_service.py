# payments/services/webhook_service.py
import hashlib
import hmac
import logging
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)


class PaystackWebhookService:
    """
    Handles all incoming Paystack webhook events.

    Events handled:
      - charge.success  → normal purchase, split initiator, split participant, marketplace
      - transfer.success / transfer.failed → payout notifications (future use)

    Security:
      - Verifies Paystack-Signature header using HMAC-SHA512
      - Idempotent — safe to receive the same event multiple times
      - All DB writes are atomic per event

    Flow:
      Paystack → POST /payments/webhook/
      WebhookView → verify signature → PaystackWebhookService.handle()
      Service → route by event type + metadata → complete the order
    """

    def __init__(self, payload: bytes, signature: str):
        self.payload   = payload
        self.signature = signature

    # ─────────────────────────────────────────────────────────────────────────
    # Entry point
    # ─────────────────────────────────────────────────────────────────────────

    def handle(self):
        self._verify_signature()

        import json
        event = json.loads(self.payload)
        event_type = event.get("event")
        data       = event.get("data", {})

        logger.info(f"Paystack webhook received: {event_type} | ref: {data.get('reference')}")

        if event_type == "charge.success":
            return self._handle_charge_success(data)

        # Other events — acknowledge but don't process yet
        logger.info(f"Unhandled webhook event type: {event_type}")
        return {"handled": False, "event": event_type}

    # ─────────────────────────────────────────────────────────────────────────
    # Signature verification
    # ─────────────────────────────────────────────────────────────────────────

    def _verify_signature(self):
        """
        Verifies the Paystack-Signature header using HMAC-SHA512.
        Raises ValueError if signature doesn't match.
        """
        secret    = settings.PAYSTACK_SECRET_KEY.encode("utf-8")
        expected  = hmac.new(secret, self.payload, hashlib.sha512).hexdigest()

        if not hmac.compare_digest(expected, self.signature):
            raise ValueError("Invalid Paystack webhook signature.")

    # ─────────────────────────────────────────────────────────────────────────
    # charge.success handler
    # ─────────────────────────────────────────────────────────────────────────

    def _handle_charge_success(self, data):
        reference = data.get("reference", "")

        if not reference:
            logger.error("Webhook charge.success received with no reference")
            return {"handled": False, "reason": "no_reference"}

        # Idempotency check — if we already processed this reference, skip
        from payments.models import Payment
        if Payment.objects.filter(provider_payment_id=reference).exists():
            logger.info(f"Webhook already processed for reference: {reference} — skipping")
            return {"handled": True, "skipped": True, "reason": "already_processed"}

        # Route to the correct flow
        flow, order, participant = self._resolve_flow(reference)

        if flow is None:
            logger.warning(f"Webhook: no order found for reference {reference}")
            return {"handled": False, "reason": "order_not_found"}

        if flow == "normal":
            return self._complete_normal(data, order)
        elif flow == "split_initiator":
            return self._complete_split_initiator(data, order, participant)
        elif flow == "split_participant":
            return self._complete_split_participant(data, participant)
        elif flow == "marketplace":
            return self._complete_marketplace(data, order)
        else:
            logger.warning(f"Webhook: unknown flow '{flow}' for reference {reference}")
            return {"handled": False, "reason": f"unknown_flow_{flow}"}

    # ─────────────────────────────────────────────────────────────────────────
    # Flow resolution — same logic as CompleteCheckoutService._find_order_and_flow
    # ─────────────────────────────────────────────────────────────────────────

    def _resolve_flow(self, reference):
        """
        Returns (flow, order, participant_or_None).
        Tries four lookup strategies matching all reference formats.
        """
        from transactions.models import Order, SplitParticipant

        # 1 — Direct match on Order.metadata.reference (normal or marketplace)
        try:
            order = Order.objects.get(metadata__reference=reference)
            flow  = order.metadata.get("flow", "normal")
            return flow, order, None
        except Order.DoesNotExist:
            pass

        # 2 — Split initiator: reference ends with _init
        if reference.endswith("_init"):
            base_ref = reference[:-5]
            try:
                order = Order.objects.get(metadata__reference=base_ref)
                return "split_initiator", order, None
            except Order.DoesNotExist:
                pass

        # 3 — Split participant: reference stored on SplitParticipant
        try:
            participant = SplitParticipant.objects.select_related(
                "split_order__order"
            ).get(payment_reference=reference)
            return "split_participant", participant.split_order.order, participant
        except SplitParticipant.DoesNotExist:
            pass

        return None, None, None

    # ─────────────────────────────────────────────────────────────────────────
    # Normal completion
    # ─────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def _complete_normal(self, data, order):
        if order.status == "completed":
            return {"handled": True, "skipped": True, "reason": "already_completed"}

        payment = self._persist_payment(data, order)
        self._finalise_order(order, payment)
        self._credit_affiliate(order)

        logger.info(f"Webhook: normal order {order.id} completed")
        return {"handled": True, "flow": "normal", "order_id": str(order.id)}

    # ─────────────────────────────────────────────────────────────────────────
    # Split initiator completion
    # ─────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def _complete_split_initiator(self, data, order, participant=None):
        from transactions.models import SplitParticipant

        split_order = order.split_order

        # Find initiator participant if not passed
        if participant is None:
            try:
                participant = split_order.participants.get(
                    payment_reference=data.get("reference")
                )
            except SplitParticipant.DoesNotExist:
                # Fall back to finding by split_order initiated_by
                try:
                    participant = split_order.participants.get(
                        user=split_order.initiated_by
                    )
                except SplitParticipant.DoesNotExist:
                    logger.error(f"Webhook: initiator participant not found for order {order.id}")
                    return {"handled": False, "reason": "participant_not_found"}

        if participant.status == "paid":
            return {"handled": True, "skipped": True, "reason": "already_paid"}

        payment = self._persist_payment(data, order)

        participant.status            = "paid"
        participant.payment           = payment
        participant.payment_reference = data.get("reference")
        participant.paid_at           = timezone.now()
        participant.save(update_fields=["status", "payment", "payment_reference", "paid_at"])

        split_order.paid_count += 1
        split_order.save(update_fields=["paid_count"])

        completed = split_order.check_completion()
        if completed:
            self._finalise_split(split_order)

        from payments.tasks import send_split_initiator_confirmation
        send_split_initiator_confirmation.delay(str(participant.id))

        logger.info(f"Webhook: split initiator paid for order {order.id}, complete={completed}")
        return {
            "handled":        True,
            "flow":           "split_initiator",
            "order_id":       str(order.id),
            "split_complete": completed,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Split participant completion
    # ─────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def _complete_split_participant(self, data, participant):
        split_order = participant.split_order

        if participant.status == "paid":
            return {"handled": True, "skipped": True, "reason": "already_paid"}

        if split_order.is_expired():
            logger.warning(f"Webhook: split order {split_order.id} expired — ignoring payment")
            return {"handled": False, "reason": "split_expired"}

        payment = self._persist_payment(data, split_order.order)

        participant.status            = "paid"
        participant.payment           = payment
        participant.payment_reference = data.get("reference")
        participant.paid_at           = timezone.now()
        participant.save(update_fields=["status", "payment", "payment_reference", "paid_at"])

        split_order.paid_count += 1
        split_order.save(update_fields=["paid_count"])

        completed = split_order.check_completion()
        if completed:
            self._finalise_split(split_order)

        logger.info(f"Webhook: split participant {participant.id} paid, complete={completed}")
        return {
            "handled":        True,
            "flow":           "split_participant",
            "participant_id": str(participant.id),
            "split_complete": completed,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Marketplace completion
    # ─────────────────────────────────────────────────────────────────────────

    @transaction.atomic
    def _complete_marketplace(self, data, order):
        from marketplace.models import MarketListing
        from attendee.models import AffliateEarnings

        if order.status == "completed":
            return {"handled": True, "skipped": True, "reason": "already_completed"}

        listing_id = order.metadata.get("listing_id")
        try:
            listing = MarketListing.objects.select_for_update().get(id=listing_id)
        except MarketListing.DoesNotExist:
            logger.error(f"Webhook: listing {listing_id} not found for order {order.id}")
            return {"handled": False, "reason": "listing_not_found"}

        if listing.status == "sold":
            return {"handled": True, "skipped": True, "reason": "already_sold"}

        # Find buyer — the order user
        buyer = order.user

        payment = self._persist_payment(data, order)

        issued_ticket                = listing.ticket
        issued_ticket.original_owner = issued_ticket.owner
        issued_ticket.owner          = buyer
        issued_ticket.status         = "resold"
        issued_ticket.transferred_at = timezone.now()
        issued_ticket.save(update_fields=["owner", "original_owner", "status", "transferred_at"])

        listing.status = "sold"
        listing.save(update_fields=["status"])

        order.status         = "completed"
        order.payment_method = "paystack"
        order.save(update_fields=["status", "payment_method"])

        # Credit seller
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

        logger.info(f"Webhook: marketplace order {order.id} completed")
        return {"handled": True, "flow": "marketplace", "order_id": str(order.id)}

    # ─────────────────────────────────────────────────────────────────────────
    # Shared helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _persist_payment(self, data, order):
        from payments.models import Payment

        currency = data.get("currency", "NGN")
        amount   = Decimal(str(data.get("amount", 0))) / 100  # kobo → naira
        reference = data.get("reference", "")

        # Idempotency — don't create duplicate payment records
        existing = Payment.objects.filter(provider_payment_id=reference).first()
        if existing:
            return existing

        return Payment.objects.create(
            user=order.user,
            email=order.email,
            card=None,   # webhook doesn't have card context
            provider="paystack",
            provider_payment_id=reference,
            amount=amount,
            currency=currency,
            status="succeeded",
            content_type=ContentType.objects.get_for_model(order),
            object_id=order.id,
            metadata={
                "reference":        reference,
                "gateway_response": data.get("gateway_response"),
                "channel":          data.get("channel"),
                "paid_at":          data.get("paid_at"),
                "source":           "webhook",
            },
        )

    def _finalise_order(self, order, payment):
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
                    owner=order.user if order.user else None,
                    guest_email=order.email if not order.user else "",
                    original_owner=order.user if order.user else None,
                    guest_original_email=order.email if not order.user else "",
                    status="active",
                    metadata={"fulfilled_by": "webhook"},
                )

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