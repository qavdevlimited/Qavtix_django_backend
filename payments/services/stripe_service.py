import stripe
from django.conf import settings
from payments.models import PaymentCard, Payment
from .base import PaymentGateway

stripe.api_key = settings.STRIPE_SECRET_KEY

class StripeGateway(PaymentGateway):

    def create_customer(self, user=None, email=None):
        """
        Returns a Stripe customer ID.
        - Authenticated users: create once and cache on user.stripe_customer_id
        - Guests: create a one-off customer using their email (not cached)
        """
        if user is not None:
            # Return existing customer if already created
            if hasattr(user, "stripe_customer_id") and user.stripe_customer_id:
                return user.stripe_customer_id

            customer = stripe.Customer.create(
                email=user.email,
                name=user.get_full_name(),
            )
            user.stripe_customer_id = customer.id
            user.save(update_fields=["stripe_customer_id"])
            return customer.id

        # Guest checkout — ephemeral customer, not saved anywhere
        if not email:
            raise ValueError("Either a user or an email is required to create a Stripe customer.")

        customer = stripe.Customer.create(email=email)
        return customer.id

    def add_card(self, user=None, payment_method_id=None, email=None):
        """
        Attaches a payment method to a Stripe customer and returns a PaymentCard.
        - Authenticated users: card is persisted to the database.
        - Guests: card object is built in memory only (not saved).
        """
        customer_id = self.create_customer(user=user, email=email)

        stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
        stripe.Customer.modify(
            customer_id,
            invoice_settings={"default_payment_method": payment_method_id},
        )

        pm = stripe.PaymentMethod.retrieve(payment_method_id)

        if user is not None:
            # Persist for authenticated users
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
            # is_default and save() are handled by the view, not here
            card.stripe_customer_id = customer_id 
            return card

        # Guest — return an unsaved in-memory card object
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
        - user/email used to resolve (or create) the Stripe customer.
        - Returns a Payment-like result object (not saved — view handles persistence).
        """
        customer_id = getattr(card, "stripe_customer_id", None)

        intent = stripe.PaymentIntent.create(
            amount=int(amount * 100),       # Stripe works in cents
            currency=currency.lower(),
            customer=customer_id,
            payment_method=card.token,
            off_session=True,
            confirm=True,
        )

        # Return a lightweight result — the view creates the Payment record
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