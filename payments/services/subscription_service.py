# payments/services/subscription_service.py
import uuid
import logging
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from payments.services.factory import get_gateway
from payments.models import Payment, PaymentCard

logger = logging.getLogger(__name__)


class SubscriptionInitiateService:
    """
    Initiates a host plan purchase.

    Rules:
      - Free plan cannot be purchased (it's the default)
      - If host already has an active non-free plan → upgrade flow:
          * Old subscription marked cancelled immediately
          * New subscription created active from today
          * Host gets new features immediately
      - If no active plan or on free → fresh purchase

    Two payment modes:
      A) card_id provided → charges saved card directly, activates immediately
      B) no card_id       → returns Paystack checkout_url for popup
    """

    def __init__(self, user, data):
        self.user     = user
        self.data     = data
        self.gateway  = get_gateway(data.get("country", "NG"))
        self.currency = data.get("currency", "NGN")

    @transaction.atomic
    def run(self):
        from payments.models import HostPlan
        from host.models import HostSubscription

        host = getattr(self.user, "host_profile", None)
        if not host:
            raise SubscriptionError("Only hosts can purchase plans.", 403)

        # Load plan
        plan_slug     = self.data.get("plan_slug")
        billing_cycle = self.data.get("billing_cycle", "monthly")

        if plan_slug == "free":
            raise SubscriptionError("Free plan cannot be purchased.", 400)

        try:
            plan = HostPlan.objects.get(slug=plan_slug, is_active=True)
        except HostPlan.DoesNotExist:
            raise SubscriptionError("Plan not found.", 404)

        # Determine price based on billing cycle
        if billing_cycle == "annual":
            amount    = plan.annual_price
            days      = 365
        else:
            amount    = plan.monthly_price
            days      = 30

        if amount <= 0:
            raise SubscriptionError("Invalid plan price.", 400)

        # Check for existing active non-free subscription
        existing = (
            host.subscriptions
            .filter(status="active")
            .exclude(plan_slug="free")
            .order_by("-started_at")
            .first()
        )

        if existing:
            # Prevent purchasing same plan again
            if existing.plan_slug == plan_slug and existing.billing_cycle == billing_cycle:
                raise SubscriptionError(
                    f"You already have an active {plan.name} {billing_cycle} plan. "
                    f"It expires on {existing.expires_at.strftime('%d %b %Y')}.",
                    400,
                )
            # Downgrade not allowed mid-cycle
            plan_rank = {"free": 0, "pro": 1, "enterprise": 2}
            if plan_rank.get(plan_slug, 0) < plan_rank.get(existing.plan_slug, 0):
                raise SubscriptionError(
                    f"You cannot downgrade to {plan.name} while your {existing.plan.name} plan is active. "
                    f"Downgrade will be available after {existing.expires_at.strftime('%d %b %Y')}.",
                    400,
                )

        reference  = f"qavtix_sub_{uuid.uuid4().hex[:16]}"
        amount_kobo = int(float(amount) * 100)
        expires_at  = timezone.now() + timezone.timedelta(days=days)

        # Create pending subscription
        subscription = HostSubscription.objects.create(
            host=host,
            plan=plan,
            plan_slug=plan_slug,
            billing_cycle=billing_cycle,
            status="pending",
            amount_paid=amount,
            expires_at=expires_at,
            metadata={
                "reference":    reference,
                "billing_cycle": billing_cycle,
                "days":          days,
            },
        )

        # Mode A — saved card: charge directly, activate now
        card_id = self.data.get("card_id")
        if card_id:
            return self._charge_saved_card(
                subscription, plan, card_id, amount_kobo, amount, reference, existing
            )

        # Mode B — popup
        init = self.gateway.initialize_transaction(
            email=self.user.email,
            amount_kobo=amount_kobo,
            currency=self.currency,
            reference=reference,
        )

        return {
            "flow":            "popup",
            "subscription_id": str(subscription.id),
            "reference":       reference,
            "checkout_url":    init["checkout_url"],
            "amount":          amount_kobo,
            "currency":        self.currency.upper(),
            "plan":            plan_slug,
            "billing_cycle":   billing_cycle,
            "expires_at":      expires_at.isoformat(),
        }

    def _charge_saved_card(self, subscription, plan, card_id, amount_kobo, amount, reference, existing):
        try:
            card = PaymentCard.objects.get(id=card_id, user=self.user)
        except PaymentCard.DoesNotExist:
            raise SubscriptionError("Card not found.", 404)

        result = self.gateway.charge_saved_card(
            card=card,
            email=self.user.email,
            amount_kobo=amount_kobo,
            currency=self.currency,
        )

        if result.status != "succeeded":
            raise SubscriptionError(
                f"Card charge failed: {result.metadata.get('gateway_response', 'Unknown error')}",
                402,
            )

        # Persist payment
        Payment.objects.create(
            user=self.user,
            email=self.user.email,
            card=card,
            provider="paystack",
            provider_payment_id=result.reference,
            amount=amount,
            currency=self.currency.upper(),
            status="succeeded",
            content_type=ContentType.objects.get_for_model(subscription),
            object_id=subscription.id,
            metadata=result.metadata,
        )

        # Activate subscription
        self._activate_subscription(subscription, existing)

        # Send activation email
        from payments.tasks import send_plan_activated_email
        send_plan_activated_email.delay(str(subscription.id))

        return {
            "flow":            "card",
            "subscription_id": str(subscription.id),
            "status":          "active",
            "plan":            plan.slug,
            "billing_cycle":   subscription.billing_cycle,
            "expires_at":      subscription.expires_at.isoformat(),
        }

    def _activate_subscription(self, subscription, existing):
        """Activates new subscription and cancels old one if upgrading."""
        # Cancel existing active non-free plan
        if existing:
            existing.status       = "cancelled"
            existing.cancelled_at = timezone.now()
            existing.save(update_fields=["status", "cancelled_at"])
            logger.info(f"Cancelled existing subscription {existing.id} for upgrade")

        # Also deactivate any other active subscriptions for this host
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
    Called after Paystack popup completes for plan purchase.
    Verifies payment, activates subscription, sends email.
    """

    def __init__(self, user, reference, save_card=False, country="NG"):
        self.user      = user
        self.reference = reference
        self.save_card = save_card
        self.gateway   = get_gateway(country)

    @transaction.atomic
    def run(self):
        from host.models import HostSubscription

        # Idempotency
        if Payment.objects.filter(provider_payment_id=self.reference).exists():
            sub = HostSubscription.objects.filter(
                metadata__reference=self.reference
            ).first()
            return {
                "already_complete": True,
                "subscription_id":  str(sub.id) if sub else None,
            }

        # Verify with Paystack
        try:
            tx = self.gateway.verify_transaction(self.reference)
        except Exception as e:
            raise SubscriptionError(f"Payment verification failed: {str(e)}", 402)

        # Find subscription
        try:
            subscription = HostSubscription.objects.select_for_update().get(
                metadata__reference=self.reference
            )
        except HostSubscription.DoesNotExist:
            raise SubscriptionError("Subscription record not found for this reference.", 404)

        if subscription.status == "active":
            return {"already_complete": True, "subscription_id": str(subscription.id)}

        # Save card if requested
        if self.user and self.save_card:
            try:
                self.gateway.save_card_from_tx(self.user, tx)
            except Exception as e:
                logger.warning(f"Card save failed during subscription completion: {e}")

        # Persist payment
        currency = tx.get("currency", "NGN")
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

        # Cancel any existing active non-free subscriptions
        from host.models import HostSubscription as HS
        HS.objects.filter(
            host=subscription.host,
            status="active",
        ).exclude(id=subscription.id).update(
            status="cancelled",
            cancelled_at=timezone.now(),
        )

        # Activate
        subscription.status = "active"
        subscription.save(update_fields=["status"])

        # Send activation email
        from payments.tasks import send_plan_activated_email
        send_plan_activated_email.delay(str(subscription.id))

        return {
            "subscription_id": str(subscription.id),
            "status":          "active",
            "plan":            subscription.plan_slug,
            "billing_cycle":   subscription.billing_cycle,
            "expires_at":      subscription.expires_at.isoformat(),
        }


class SubscriptionError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)