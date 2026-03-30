# payments/services/subscription_service.py
import uuid
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from payments.services.factory import get_gateway
from payments.models import Payment, PaymentCard
from payments.services.currency_utils import get_gateway_country_code

logger = logging.getLogger(__name__)


class SubscriptionInitiateService:
    """
    Initiates a host plan purchase with user-selected currency support.

    Frontend can now pass "currency": "USD" or "NGN" etc.
    The chosen currency is used for Paystack and stored in the subscription.
    """

    def __init__(self, user, data):
        self.user      = user
        self.data      = data
        self.currency  = data.get("currency", "NGN").upper()          # ← User chosen
        self.gateway   = get_gateway(get_gateway_country_code(self.currency))

    @transaction.atomic
    def run(self):
        from payments.models import HostPlan
        from host.models import HostSubscription

        host = getattr(self.user, "host_profile", None)
        if not host:
            raise SubscriptionError("Only hosts can purchase plans.", 403)

        plan_slug     = self.data.get("plan_slug")
        billing_cycle = self.data.get("billing_cycle", "monthly")

        if plan_slug == "free":
            raise SubscriptionError("Free plan cannot be purchased.", 400)

        try:
            plan = HostPlan.objects.get(slug=plan_slug, is_active=True)
        except HostPlan.DoesNotExist:
            raise SubscriptionError("Plan not found.", 404)

        # Determine base price (you can later add currency conversion here if needed)
        if billing_cycle == "annual":
            amount    = plan.annual_price
            days      = 365
        else:
            amount    = plan.monthly_price
            days      = 30

        if amount <= 0:
            raise SubscriptionError("Invalid plan price.", 400)

        # === Existing Plan Validation (unchanged) ===
        existing = (
            host.subscriptions
            .filter(status="active")
            .exclude(plan_slug="free")
            .order_by("-started_at")
            .first()
        )

        if existing:
            if existing.plan_slug == plan_slug and existing.billing_cycle == billing_cycle:
                raise SubscriptionError(
                    f"You already have an active {plan.name} {billing_cycle} plan. "
                    f"It expires on {existing.expires_at.strftime('%d %b %Y')}.",
                    400,
                )

            plan_rank = {"free": 0, "pro": 1, "enterprise": 2}
            if plan_rank.get(plan_slug, 0) < plan_rank.get(existing.plan_slug, 0):
                raise SubscriptionError(
                    f"You cannot downgrade to {plan.name} while your {existing.plan.name} plan is active.",
                    400,
                )

        reference   = f"qavtix_sub_{uuid.uuid4().hex[:16]}"
        expires_at  = timezone.now() + timezone.timedelta(days=days)

        # Create pending subscription with chosen currency
        subscription = HostSubscription.objects.create(
            host=host,
            plan=plan,
            plan_slug=plan_slug,
            billing_cycle=billing_cycle,
            status="pending",
            amount_paid=amount,
            currency=self.currency,                    # ← Store chosen currency
            expires_at=expires_at,
            metadata={
                "reference":     reference,
                "billing_cycle": billing_cycle,
                "days":          days,
                "currency":      self.currency,
            },
        )

        # Mode A — Direct charge with saved card
        card_id = self.data.get("card_id")
        if card_id:
            return self._charge_saved_card(
                subscription, plan, card_id, amount, reference, existing
            )

        # Mode B — Paystack Popup
        amount_in_smallest_unit = int(float(amount) * 100)   # Paystack expects kobo/pesewas/cents

        init = self.gateway.initialize_transaction(
            email=self.user.email,
            amount_kobo=amount_in_smallest_unit,
            currency=self.currency,                       # ← Use user-selected currency
            reference=reference,
            metadata={
                "flow": "subscription",
                "subscription_id": str(subscription.id),
            }
        )

        return {
            "flow":            "popup",
            "subscription_id": str(subscription.id),
            "reference":       reference,
            "checkout_url":    init["checkout_url"],
            "amount":          amount,                    # base amount
            "currency":        self.currency,
            "plan":            plan_slug,
            "billing_cycle":   billing_cycle,
            "expires_at":      expires_at.isoformat(),
        }

    def _charge_saved_card(self, subscription, plan, card_id, amount, reference, existing):
        try:
            card = PaymentCard.objects.get(id=card_id, user=self.user)
        except PaymentCard.DoesNotExist:
            raise SubscriptionError("Card not found.", 404)

        result = self.gateway.charge_saved_card(
            card=card,
            email=self.user.email,
            amount_kobo=int(float(amount) * 100),
            currency=self.currency,
        )

        if result.status != "succeeded":
            raise SubscriptionError(
                f"Card charge failed: {result.metadata.get('gateway_response', 'Unknown error')}",
                402,
            )

        # Persist payment with correct currency
        Payment.objects.create(
            user=self.user,
            email=self.user.email,
            card=card,
            provider="paystack",
            provider_payment_id=result.reference,
            amount=amount,
            currency=self.currency,
            status="succeeded",
            content_type=ContentType.objects.get_for_model(subscription),
            object_id=subscription.id,
            metadata=result.metadata,
        )

        self._activate_subscription(subscription, existing)

        from payments.tasks import send_plan_activated_email
        send_plan_activated_email.delay(str(subscription.id))

        return {
            "flow":            "card",
            "subscription_id": str(subscription.id),
            "status":          "active",
            "plan":            plan.slug,
            "billing_cycle":   subscription.billing_cycle,
            "expires_at":      subscription.expires_at.isoformat(),
            "currency":        self.currency,
        }

    def _activate_subscription(self, subscription, existing):
        if existing:
            existing.status       = "cancelled"
            existing.cancelled_at = timezone.now()
            existing.save(update_fields=["status", "cancelled_at"])

        # Deactivate any other active subscriptions
        from host.models import HostSubscription
        HostSubscription.objects.filter(
            host=subscription.host,
            status="active",
        ).exclude(id=subscription.id).update(
            status="cancelled",
            cancelled_at=timezone.now(),
        )

        subscription.status = "active"
        subscription.save(update_fields=["status"])


class CompleteSubscriptionService:
    """
    Completes subscription after Paystack popup.
    Now respects the currency stored in the subscription.
    """

    def __init__(self, user, reference, save_card=False, country="NG"):
        self.user      = user
        self.reference = reference
        self.save_card = save_card
        self.gateway   = get_gateway(country)

    @transaction.atomic
    def run(self):
        from host.models import HostSubscription

        # Idempotency check
        if Payment.objects.filter(provider_payment_id=self.reference).exists():
            sub = HostSubscription.objects.filter(
                metadata__reference=self.reference
            ).first()
            return {
                "already_complete": True,
                "subscription_id": str(sub.id) if sub else None,
            }

        try:
            tx = self.gateway.verify_transaction(self.reference)
        except Exception as e:
            raise SubscriptionError(f"Payment verification failed: {str(e)}", 402)

        try:
            subscription = HostSubscription.objects.select_for_update().get(
                metadata__reference=self.reference
            )
        except HostSubscription.DoesNotExist:
            raise SubscriptionError("Subscription record not found.", 404)

        if subscription.status == "active":
            return {"already_complete": True, "subscription_id": str(subscription.id)}

        # Save card if requested
        if self.user and self.save_card:
            try:
                self.gateway.save_card_from_tx(self.user, tx)
            except Exception as e:
                logger.warning(f"Failed to save card: {e}")

        # Use currency from transaction (Paystack) or fallback to stored one
        currency = tx.get("currency") or subscription.currency or "NGN"
        amount   = Decimal(str(tx.get("amount", 0))) / 100

        Payment.objects.create(
            user=self.user,
            email=self.user.email,
            provider="paystack",
            provider_payment_id=tx.get("reference", self.reference),
            amount=amount,
            currency=currency,
            status="succeeded",
            content_type=ContentType.objects.get_for_model(subscription),
            object_id=subscription.id,
            metadata={
                "reference":        tx.get("reference"),
                "gateway_response": tx.get("gateway_response"),
                "channel":          tx.get("channel"),
                "paid_at":          tx.get("paid_at"),
            },
        )

        # Activate subscription
        self._activate_subscription(subscription)

        from payments.tasks import send_plan_activated_email
        send_plan_activated_email.delay(str(subscription.id))

        return {
            "subscription_id": str(subscription.id),
            "status":          "active",
            "plan":            subscription.plan_slug,
            "billing_cycle":   subscription.billing_cycle,
            "expires_at":      subscription.expires_at.isoformat(),
            "currency":        currency,
        }

    def _activate_subscription(self, subscription):
        from host.models import HostSubscription

        # Cancel all other active subscriptions
        HostSubscription.objects.filter(
            host=subscription.host,
            status="active",
        ).exclude(id=subscription.id).update(
            status="cancelled",
            cancelled_at=timezone.now(),
        )

        subscription.status = "active"
        subscription.save(update_fields=["status"])


class SubscriptionError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)