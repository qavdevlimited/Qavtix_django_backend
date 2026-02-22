import stripe
from django.conf import settings
from payments.models import PaymentCard, Payment
from .base import PaymentGateway

stripe.api_key = settings.STRIPE_SECRET_KEY

class StripeGateway(PaymentGateway):

    # payments/services/stripe.py
    def create_customer(self, user=None, email=None):
        """
        Returns a Stripe customer ID.
        """
        profile = getattr(user, "attendee_profile", None) or getattr(user, "host_profile", None)

        if profile and profile.stripe_customer_id:
            return profile.stripe_customer_id

        if user is not None:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.get_full_name(),
            )
            if profile:
                profile.stripe_customer_id = customer.id
                profile.save(update_fields=["stripe_customer_id"])
            return customer.id

        # Guest checkout — ephemeral customer, not saved anywhere
        if not email:
            raise ValueError("Either a user or an email is required to create a Stripe customer.")

        customer = stripe.Customer.create(email=email)
        return customer.id

    def add_card(self, user=None, payment_method_id=None, email=None):
        """
        Attaches a payment method to a Stripe customer and returns a PaymentCard.
        Ensures each card is unique per user.
        - Authenticated users: card is persisted to the database.
        - Guests: card object is built in memory only (not saved).
        """
        profile = getattr(user, "attendee_profile", None) or getattr(user, "host_profile", None)

        # Ensure customer exists
        customer_id = profile.stripe_customer_id if profile else None
        if user and not customer_id:
            customer_id = self.create_customer(user=user, email=email)
            if profile:
                profile.stripe_customer_id = customer_id
                profile.save(update_fields=["stripe_customer_id"])

        # Retrieve PaymentMethod details
        pm = stripe.PaymentMethod.retrieve(payment_method_id)

        # Check if user already has this card
        if user:
            existing_card = PaymentCard.objects.filter(
                user=user,
                last4=pm.card.last4,
                exp_month=pm.card.exp_month,
                exp_year=pm.card.exp_year,
                brand=pm.card.brand,
                provider="stripe"
            ).first()
            if existing_card:
                # Update default if needed
                if not existing_card.is_default:
                    PaymentCard.objects.filter(user=user).update(is_default=False)
                    existing_card.is_default = True
                    existing_card.save(update_fields=["is_default"])
                return existing_card

            # Attach card to Stripe customer
            stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
            stripe.Customer.modify(
                customer_id,
                invoice_settings={"default_payment_method": payment_method_id},
            )

            # Persist new card
            card = PaymentCard(
                user=user,
                provider="stripe",
                token=pm.id,
                brand=pm.card.brand,
                last4=pm.card.last4,
                exp_month=pm.card.exp_month,
                exp_year=pm.card.exp_year,
                is_default=True,
            )
            card.stripe_customer_id = customer_id
            return card

        # Guest — just build in-memory card object
        card = PaymentCard(
            user=None,
            provider="stripe",
            token=pm.id,
            brand=pm.card.brand,
            last4=pm.card.last4,
            exp_month=pm.card.exp_month,
            exp_year=pm.card.exp_year,
            is_default=False,
        )
        card.stripe_customer_id = customer_id
        return card
    def charge_card(self, card: PaymentCard, amount, currency="USD", user=None, email=None):
        """
        Charges a card via Stripe PaymentIntents.
        """
        # Get the Stripe customer ID properly
        if user:
            profile = getattr(user, "attendee_profile", None) or getattr(user, "host_profile", None)
            customer_id = profile.stripe_customer_id if profile else None
            if not customer_id:
                customer_id = self.create_customer(user=user, email=email)
                if profile:
                    profile.stripe_customer_id = customer_id
                    profile.save(update_fields=["stripe_customer_id"])
        else:
            # Guest — use card's stored stripe_customer_id if any
            customer_id = getattr(card, "stripe_customer_id", None)
            if not customer_id and not email:
                raise ValueError("Cannot charge card: no customer info available")
            if not customer_id:
                customer_id = self.create_customer(user=None, email=email)

        intent = stripe.PaymentIntent.create(
            amount=int(amount * 100),       # cents
            currency=currency.lower(),
            customer=customer_id,
            payment_method=card.token,
            off_session=True,
            confirm=True,
        )

        return _PaymentResult(
            id=intent.id,
            status=intent.status,
            metadata={"client_secret": getattr(intent, "client_secret", None)},
        )

class _PaymentResult:
    def __init__(self, id, status, metadata=None):
        self.id = id
        self.status = status
        self.metadata = metadata or {}