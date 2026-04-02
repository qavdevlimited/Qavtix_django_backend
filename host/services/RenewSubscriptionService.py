from django.utils import timezone
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
import uuid
from payments.models import Payment, PaymentCard
from payments.services.factory import get_gateway
from payments.services.currency_utils import get_gateway_country_code
from host.models import HostSubscription
from payments.tasks import send_plan_activated_email


class SubscriptionError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status
        super().__init__(message)


class RenewSubscriptionService:
    """
    Renews the host's active plan only if it's close to expiry (<=3 days remaining).
    The new subscription will start immediately after the old one expires.
    """
    RENEWAL_WINDOW_DAYS = 3

    def __init__(self, user):
        self.user = user

    @transaction.atomic
    def run(self):
        host = getattr(self.user, "host_profile", None)
        if not host:
            raise SubscriptionError("Only hosts can renew subscriptions.", 403)

        # Get latest active subscription
        current = (
            host.subscriptions
            .filter(status="active")
            .exclude(plan_slug="free")   # ignore free plans
            .order_by("-started_at")
            .first()
        )

        if not current:
            raise SubscriptionError("No active subscription to renew.", 404)

        if current.plan_slug == "free":
            raise SubscriptionError("Free plan cannot be renewed.", 400)

        # Check remaining days
        remaining_days = (current.expires_at - timezone.now()).days
        if remaining_days > self.RENEWAL_WINDOW_DAYS:
            raise SubscriptionError(
                f"You can only renew your plan within {self.RENEWAL_WINDOW_DAYS} days of expiry. "
                f"Remaining days: {remaining_days}"
            )

        # Get default card
        card = PaymentCard.objects.filter(user=self.user, is_default=True).first()
        if not card:
            raise SubscriptionError("No default card found.", 400)

        # Determine price and new expiry
        if current.billing_cycle == "annual":
            amount = current.plan.annual_price
            duration_days = 365
        else:
            amount = current.plan.monthly_price
            duration_days = 30

        reference = f"qavtix_renew_{uuid.uuid4().hex[:16]}"
        new_expires_at = current.expires_at + timezone.timedelta(days=duration_days)

        # Create new subscription **pending activation**
        new_sub = HostSubscription.objects.create(
            host=host,
            plan=current.plan,
            plan_slug=current.plan_slug,
            billing_cycle=current.billing_cycle,
            status="pending",
            amount_paid=amount,
            currency=current.currency,
            started_at=current.expires_at,  # will start when old plan ends
            expires_at=new_expires_at,
            metadata={
                "reference": reference,
                "renewal": True,
            },
        )

        # Charge the default card immediately
        gateway = get_gateway(get_gateway_country_code(current.currency))
        result = gateway.charge_saved_card(
            card=card,
            email=self.user.email,
            amount_kobo=int(float(amount) * 100),
            currency=current.currency,
        )

        if result.status != "succeeded":
            new_sub.delete()  # rollback if payment fails
            raise SubscriptionError(
                f"Renewal failed: {result.metadata.get('gateway_response', 'Unknown error')}",
                402,
            )

        # Save payment record
        Payment.objects.create(
            user=self.user,
            email=self.user.email,
            card=card,
            provider="paystack",
            provider_payment_id=result.reference,
            amount=amount,
            currency=current.currency,
            status="succeeded",
            content_type=ContentType.objects.get_for_model(new_sub),
            object_id=new_sub.id,
            metadata=result.metadata,
        )

        # Notify user (email will mention new plan will start after current ends)
        send_plan_activated_email.delay(str(new_sub.id))

        return {
            "subscription_id": str(new_sub.id),
            "status": "pending",
            "plan": new_sub.plan_slug,
            "billing_cycle": new_sub.billing_cycle,
            "starts_at": new_sub.started_at.isoformat(),
            "expires_at": new_sub.expires_at.isoformat(),
            "currency": new_sub.currency,
            "renewed": True,
            "message": f"Your renewal is successful and will start after your current plan expires ({current.expires_at.date()})."
        }