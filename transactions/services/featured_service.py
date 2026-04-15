# payments/services/featured_service.py
import uuid
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from host.models import FeatureUsage
from host.plan_limits import get_host_plan_slug
from payments.services.factory import get_gateway
from payments.services.currency_service import CurrencyService
from payments.models import PaymentCard, Payment

logger = logging.getLogger(__name__)


class FeaturedInitiateService:
    """
    Initiates a featured event payment.

    Three modes:
      A) card_id provided → charges saved card directly, activates immediately
      B) no card_id       → returns Paystack checkout_url for popup
      C) currency conversion → converts NGN amount to target currency if needed

    In all cases FeaturedEvent is created in "pending" state first,
    then activated on successful payment — inside same transaction.
    """

    def __init__(self, user, data):
        self.user     = user
        self.data     = data
        self.gateway  = get_gateway(data.get("country", "NG"))
        self.currency = data.get("currency", "NGN")

    @transaction.atomic
    def run(self):
        from transactions.models import FeaturedPlan, FeaturedEvent
        from events.models import Event

        # Load and validate event ownership
        try:
            event = Event.objects.select_for_update().get(id=self.data["event_id"])
        except Event.DoesNotExist:
            raise FeaturedError("Event not found.", 404)

        if event.host.user != self.user:
            raise FeaturedError("You can only feature your own events.", 403)

        if event.status not in ("active", "draft"):
            raise FeaturedError(
                f"Event cannot be featured (status: {event.status}).", 400
            )

        # Prevent double featuring — one active plan per event at a time
        already_active = FeaturedEvent.objects.filter(
            event=event,
            status="active",
            end_date__gt=timezone.now(),
        ).exists()

        if already_active:
            raise FeaturedError(
                "This event already has an active featured plan. "
                "You can purchase a new one after the current one expires.",
                400,
            )

        # Load plan
        try:
            plan = FeaturedPlan.objects.get(
                slug=self.data["plan_slug"],
                is_active=True,
            )
        except FeaturedPlan.DoesNotExist:
            raise FeaturedError("Featured plan not found.", 404)
        
        plan_slug = get_host_plan_slug(event.host)

        if plan_slug == "enterprise":
            sub = (
                event.host.subscriptions
                .select_for_update()
                .filter(status="active")
                .first()
            )

            if sub is not None:
                usage, _ = FeatureUsage.objects.select_for_update().get_or_create(
                    host=event.host,
                    subscription=sub,
                )

                if not usage.featured_used:
                    now = timezone.now()
                    FREE_DAYS = 14

                    featured = FeaturedEvent.objects.create(
                        event=event,
                        user=self.user,
                        end_date=now + timezone.timedelta(days=FREE_DAYS),
                        payment_amount=Decimal("0.00"),
                        payment_method="free_quota",
                        status="active",
                        metadata={
                            "reference": f"free_feat_{uuid.uuid4().hex[:12]}",
                            "plan_slug": plan.slug,
                            "flow": "featured",
                            "duration_days": FREE_DAYS,
                            "free_quota_used": True,
                            "completed_by": "enterprise_free",
                            "original_price": str(plan.price),
                        },
                    )

                    usage.featured_used = True
                    usage.save(update_fields=["featured_used"])

                    from transactions.tasks import send_featured_activation_email
                    send_featured_activation_email.delay(str(featured.id))

                    return {
                        "flow": "free",
                        "featured_id": str(featured.id),
                        "status": "active",
                        "message": "Activated using your free 2-week enterprise quota.",
                        "expires_at": featured.end_date.isoformat(),
                    }

        # Get plan price in NGN (base currency)
        plan_price_ngn = Decimal(str(plan.price))
        
        # Handle currency conversion if needed
        amount_kobo = int(float(plan_price_ngn) * 100)
        display_amount = plan_price_ngn
        display_currency = "NGN"

        if self.currency and self.currency.upper() != "NGN":
            try:
                display_amount = CurrencyService.convert_to_currency(
                    plan_price_ngn,
                    self.currency
                )
                display_currency = self.currency.upper()
                logger.info(
                    f"Currency conversion: {plan_price_ngn} NGN → {display_amount} {display_currency}"
                )
            except Exception as e:
                logger.warning(
                    f"Currency conversion failed for {self.currency}, falling back to NGN: {e}"
                )
                self.currency = "NGN"
                display_amount = plan_price_ngn
                display_currency = "NGN"

        reference   = f"qavtix_feat_{uuid.uuid4().hex[:16]}"
        end_date    = timezone.now() + timezone.timedelta(days=plan.duration_days)

        # Create FeaturedEvent in pending state
        featured = FeaturedEvent.objects.create(
            event=event,
            user=self.user,
            end_date=end_date,
            payment_amount=plan_price_ngn,  # Store in NGN (base currency)
            payment_method=None,
            status="pending",
            metadata={
                "reference":          reference,
                "plan_slug":          plan.slug,
                "flow":               "featured",
                "duration_days":      plan.duration_days,
                "reminder_sent":      False,
                "original_currency":  "NGN",
                "display_currency":   display_currency,
                "display_amount":     str(display_amount),
            },
        )

        # Mode A — saved card: charge directly, activate now
        card_id = self.data.get("card_id")
        if card_id:
            return self._charge_saved_card(
                featured, plan, card_id, amount_kobo, reference, display_currency, display_amount
            )

        # Mode B — popup: initialize Paystack transaction
        init = self.gateway.initialize_transaction(
            email=self.user.email,
            amount_kobo=amount_kobo,
            currency=self.currency,
            reference=reference,
        )

        return {
            "flow":            "popup",
            "featured_id":     str(featured.id),
            "reference":       reference,
            "checkout_url":    init["checkout_url"],
            "amount":          amount_kobo,
            "display_amount":  str(display_amount),
            "currency":        self.currency.upper(),
            "display_currency": display_currency,
            "plan":            plan.slug,
            "duration_days":   plan.duration_days,
            "expires_at":      end_date.isoformat(),
        }

    def _charge_saved_card(self, featured, plan, card_id, amount_kobo, reference, display_currency, display_amount):
        """Charges saved card and activates featured in the same atomic block."""
        try:
            card = PaymentCard.objects.get(id=card_id, user=self.user)
        except PaymentCard.DoesNotExist:
            raise FeaturedError("Card not found.", 404)

        result = self.gateway.charge_saved_card(
            card=card,
            email=self.user.email,
            amount_kobo=amount_kobo,
            currency=self.currency,
        )

        if result.status != "succeeded":
            raise FeaturedError(
                f"Card charge failed: {result.metadata.get('gateway_response', 'Unknown error')}",
                402,
            )

        # Persist payment linked to FeaturedEvent via GenericForeignKey
        Payment.objects.create(
            user=self.user,
            email=self.user.email,
            card=card,
            provider="paystack",
            provider_payment_id=result.reference,
            amount=Decimal(str(amount_kobo)) / 100,  # Convert kobo back to NGN
            currency="NGN",
            status="succeeded",
            content_type=ContentType.objects.get_for_model(featured),
            object_id=featured.id,
            metadata={
                **result.metadata,
                "display_currency": display_currency,
                "display_amount": str(display_amount),
                "original_amount_ngn": str(Decimal(str(amount_kobo)) / 100),
            },
        )

        # Activate
        featured.status         = "active"
        featured.payment_method = "paystack"
        featured.metadata["completed_by"] = "card_charge"
        featured.metadata["display_currency"] = display_currency
        featured.metadata["display_amount"] = str(display_amount)
        featured.save(update_fields=["status", "payment_method", "metadata"])

        # Send activation email via Celery
        from transactions.tasks import send_featured_activation_email
        send_featured_activation_email.delay(str(featured.id))

        logger.info(
            f"Featured event activated via saved card: {featured.id} "
            f"(Charged: {display_amount} {display_currency})"
        )

        return {
            "flow":            "card",
            "featured_id":     str(featured.id),
            "status":          "active",
            "plan":            plan.slug,
            "duration_days":   plan.duration_days,
            "display_amount":  str(display_amount),
            "display_currency": display_currency,
            "expires_at":      featured.end_date.isoformat(),
        }


class CompleteFeaturedService:
    """
    Called after Paystack popup completes.
    Verifies payment, activates FeaturedEvent, sends email.
    
    Supports multi-currency flows with automatic conversion logging.
    """

    def __init__(self, user, reference, save_card=False, country="NG", target_currency="NGN"):
        self.user             = user
        self.reference        = reference
        self.save_card        = save_card
        self.gateway          = get_gateway(country)
        self.target_currency  = target_currency.upper() if target_currency else "NGN"

    @transaction.atomic
    def run(self):
        from transactions.models import FeaturedEvent

        # Idempotency — already processed
        if Payment.objects.filter(provider_payment_id=self.reference).exists():
            featured = FeaturedEvent.objects.filter(
                metadata__reference=self.reference
            ).first()
            logger.info(f"Payment already processed: {self.reference}")
            return {
                "already_complete": True,
                "featured_id": str(featured.id) if featured else None,
            }

        # Verify with Paystack
        try:
            tx = self.gateway.verify_transaction(self.reference)
        except Exception as e:
            logger.error(f"Payment verification failed: {str(e)}")
            raise FeaturedError(f"Payment verification failed: {str(e)}", 402)

        # Find FeaturedEvent by reference
        try:
            featured = FeaturedEvent.objects.select_for_update().get(
                metadata__reference=self.reference
            )
        except FeaturedEvent.DoesNotExist:
            raise FeaturedError("Featured record not found for this reference.", 404)

        if featured.status == "active":
            logger.info(f"Featured already active: {featured.id}")
            return {"already_complete": True, "featured_id": str(featured.id)}

        # Save card if requested
        if self.user and self.save_card:
            try:
                self.gateway.save_card_from_tx(self.user, tx)
                logger.info(f"Card saved for user {self.user.id}")
            except Exception as e:
                logger.warning(f"Card save failed during featured completion: {e}")

        # Extract payment details
        currency = tx.get("currency", "NGN").upper()
        amount_ngn = Decimal(str(tx.get("amount", 0))) / 100

        # Handle currency conversion if needed
        display_amount = amount_ngn
        display_currency = "NGN"

        if currency and currency != "NGN":
            try:
                # If payment was in another currency, we might need to convert back or log it
                display_amount = amount_ngn
                display_currency = currency
                logger.info(
                    f"Payment received in {currency}: {display_amount} "
                    f"(equivalent to {amount_ngn} NGN)"
                )
            except Exception as e:
                logger.warning(f"Currency conversion issue in completion: {e}")

        # Persist payment
        Payment.objects.create(
            user=self.user,
            email=self.user.email,
            provider="paystack",
            provider_payment_id=tx.get("reference", self.reference),
            amount=amount_ngn,  # Store in NGN
            currency="NGN",
            status="succeeded",
            content_type=ContentType.objects.get_for_model(featured),
            object_id=featured.id,
            metadata={
                "reference":        tx.get("reference"),
                "gateway_response": tx.get("gateway_response"),
                "channel":          tx.get("channel"),
                "paid_at":          tx.get("paid_at"),
                "display_currency": display_currency,
                "display_amount":   str(display_amount),
            },
        )

        # Activate
        featured.status         = "active"
        featured.payment_method = "paystack"
        featured.metadata["completed_by"] = "popup"
        featured.metadata["display_currency"] = display_currency
        featured.metadata["display_amount"] = str(display_amount)
        featured.save(update_fields=["status", "payment_method", "metadata"])

        # Send activation email
        from transactions.tasks import send_featured_activation_email
        send_featured_activation_email.delay(str(featured.id))

        logger.info(
            f"Featured event activated via popup: {featured.id} "
            f"(Paid: {display_amount} {display_currency})"
        )

        return {
            "featured_id":      str(featured.id),
            "status":           "active",
            "display_amount":   str(display_amount),
            "display_currency": display_currency,
            "expires_at":       featured.end_date.isoformat(),
        }


class FeaturedError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)