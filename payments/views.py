# payments/views.py
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from payments.services.factory import get_gateway
from payments.models import PaymentCard, Payment
from payments.serializers import *
from payments.services.checkout_service import CheckoutService, CheckoutError
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from decimal import Decimal
from django.utils import timezone
from public.response import flatten_errors,api_response
from stripe import StripeError, InvalidRequestError
from drf_spectacular.utils import extend_schema, inline_serializer,OpenApiParameter
from rest_framework import serializers


class CheckoutView(APIView):
    """
    POST /payments/checkout/

    Initiates a payment. Returns a Paystack checkout_url to redirect/popup.
    Works for all three flows: normal, split, marketplace.
    """
    permission_classes = [AllowAny]
    @extend_schema(
        summary="Initiate payment",
        description="""
Initiates a Paystack payment for one of three flows:

**Normal purchase** — buy tickets directly from an event.

**Split purchase** — split ticket cost with friends. All members must have QavTix accounts.
Initiator pays their share immediately, others receive payment links via email.
Number of split_members must equal total ticket quantity.

**Marketplace purchase** — buy a resale ticket from the marketplace.
Use marketplace_listing_id instead of event_id + tickets.
        """,
        request=CheckoutSerializer,
        responses={
            200: OpenApiResponse(description="Payment initiated — proceed to checkout_url"),
            400: OpenApiResponse(description="Validation error"),
            401: OpenApiResponse(description="Authentication required"),
        },
        examples=[
            OpenApiExample(
                "Normal purchase",
                value={
                    "country": "NG",
                    "currency": "NGN",
                    "full_name": "John Doe",
                    "phone_number": "08012345678",
                    "is_split": False,
                    "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "tickets": [{"ticket_id": 1, "quantity": 2}],
                    "promo_code": "",
                    "save_card": True,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Split purchase",
                value={
                    "country": "NG",
                    "currency": "NGN",
                    "full_name": "John Doe",
                    "phone_number": "08012345678",
                    "is_split": True,
                    "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "tickets": [{"ticket_id": 1, "quantity": 3}],
                    "promo_code": "",
                    "save_card": True,
                    "split_members": [
                        {"email": "john@example.com",  "percentage": "33.34"},
                        {"email": "jane@example.com",  "percentage": "33.33"},
                        {"email": "mark@example.com",  "percentage": "33.33"},
                    ],
                },
                request_only=True,
            ),
            OpenApiExample(
                "Marketplace purchase",
                value={
                    "country": "NG",
                    "currency": "NGN",
                    "full_name": "John Doe",
                    "phone_number": "08012345678",
                    "is_split": False,
                    "marketplace_listing_id": 5,
                    "tickets": [],
                    "save_card": True,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Guest purchase",
                value={
                    "country": "NG",
                    "currency": "NGN",
                    "full_name": "John Doe",
                    "phone_number": "08012345678",
                    "email": "john@example.com",
                    "is_split": False,
                    "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "tickets": [{"ticket_id": 1, "quantity": 1}],
                    "promo_code": "",
                    "save_card": False,
                },
                request_only=True,
            ),
        ],
    )
    @transaction.atomic
    def post(self, request):
        from payments.serializers import CheckoutSerializer
        from payments.services.checkout_service import CheckoutService, CheckoutError

        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user  = request.user if request.user.is_authenticated else None
        email = user.email if user else data.get("email")

        if not email:
            return api_response(message="Email is required for guest checkout.", status_code=400)

        # Split requires auth
        if data.get("is_split") and not user:
            return api_response(message="Authentication required for split payment.", status_code=401)

        try:
            result = CheckoutService(user=user, email=email, data=data).run()
        except CheckoutError as e:
            transaction.set_rollback(True)
            return api_response(message=e.message, status_code=e.status)
        except Exception as e:
            transaction.set_rollback(True)
            return api_response(message=f"Checkout failed: {str(e)}", status_code=500)

        return api_response(
            message="Payment initiated. Complete payment at the checkout URL.",
            status_code=200,
            data=result,
        )


class CompleteCheckoutView(APIView):
    """
    POST /payments/complete/

    Called after user completes payment on Paystack.
    Verifies payment, issues tickets, completes order.
    """
    permission_classes = [AllowAny]
    @extend_schema(
        summary="Complete payment after Paystack popup",
        description="""
Call this immediately after the Paystack popup `callback` fires with a reference.
Verifies the transaction with Paystack, issues tickets, and completes the order.

**Works for all flows** — normal, split initiator, split participant, and marketplace.
The service determines the correct flow from the transaction metadata automatically.

**Split note:** For split payments, tickets are only issued when ALL participants have paid.
Calling this for an initiator just marks their share as paid and sends emails to others.
        """,
        request=CompleteCheckoutSerializer,
        responses={
            200: inline_serializer(
                name="CompleteCheckoutResponse",
                fields={
                    "status":  serializers.CharField(),
                    "message": serializers.CharField(),
                    "data":    inline_serializer(
                        name="CompleteCheckoutData",
                        fields={
                            "flow":           serializers.CharField(),
                            "order_id":       serializers.CharField(),
                            "status":         serializers.CharField(),
                            "split_complete": serializers.BooleanField(required=False),
                            "paid_count":     serializers.IntegerField(required=False),
                            "total":          serializers.IntegerField(required=False),
                        }
                    ),
                }
            ),
            402: OpenApiResponse(description="Payment verification failed — Paystack rejected the reference"),
            404: OpenApiResponse(description="Order not found"),
            500: OpenApiResponse(description="Completion failed"),
        },
        examples=[
            OpenApiExample(
                "Normal / Marketplace — auth user",
                summary="Auth user completing normal or marketplace purchase",
                value={
                    "reference": "qavtix_abc123def456",
                    "save_card": True,
                    "country":   "NG",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Normal — guest user",
                summary="Guest user — email required",
                value={
                    "reference": "qavtix_abc123def456",
                    "save_card": False,
                    "country":   "NG",
                    "email":     "john@example.com",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Split initiator",
                summary="Initiator completing their share of a split",
                value={
                    "reference": "qavtix_abc123def456_init",
                    "save_card": True,
                    "country":   "NG",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Split participant",
                summary="Non-initiator completing their share after clicking email link",
                value={
                    "reference": "qavtix_split_abc123def456",
                    "save_card": True,
                    "country":   "NG",
                },
                request_only=True,
            ),
        ],
    )
    @transaction.atomic
    def post(self, request):
        from payments.serializers import CompleteCheckoutSerializer
        from payments.services.checkout_service import CompleteCheckoutService, CheckoutError

        serializer = CompleteCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user  = request.user if request.user.is_authenticated else None
        email = user.email if user else data.get("email")

        try:
            result = CompleteCheckoutService(
                user=user,
                email=email,
                reference=data["reference"],
                save_card=data.get("save_card", False),
                country=data.get("country", "NG"),
            ).run()
        except CheckoutError as e:
            transaction.set_rollback(True)
            return api_response(message=e.message, status_code=e.status)
        except Exception as e:
            transaction.set_rollback(True)
            return api_response(message=f"Completion failed: {str(e)}", status_code=500)

        return api_response(
            message="Payment confirmed. Tickets issued.",
            status_code=200,
            data=result,
        )


class SplitPayView(APIView):
    """
    GET  /payments/split/pay/<pay_token>/  — returns participant + amount info
    POST /payments/split/pay/<pay_token>/  — initiates their Paystack payment
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get split payment details",
        description="Returns the participant's share amount and event info. "
                    "The pay_token comes from the email link sent to the participant.",
        responses={
            200: OpenApiResponse(description="Split payment details"),
            400: OpenApiResponse(description="Already paid or expired"),
            404: OpenApiResponse(description="Invalid token"),
        },
    )
    def get(self, request, pay_token):
        from transactions.models import SplitParticipant

        try:
            participant = SplitParticipant.objects.select_related(
                "split_order__order__event", "user"
            ).get(pay_token=pay_token, user=request.user)
        except SplitParticipant.DoesNotExist:
            return api_response(message="Invalid or expired payment link.", status_code=404)

        if participant.split_order.is_expired():
            return api_response(message="This split payment has expired.", status_code=400)

        if participant.status == "paid":
            return api_response(message="You have already paid.", status_code=400)

        event = participant.split_order.order.event
        return api_response(
            message="Split payment details",
            status_code=200,
            data={
                "participant_id": str(participant.id),
                "event":          event.title,
                "event_date":     event.start_datetime,
                "your_share":     str(participant.amount),
                "percentage":     str(participant.percentage),
                "expires_at":     participant.split_order.expires_at,
                "paid_count":     participant.split_order.paid_count,
                "total":          participant.split_order.total_participants,
            },
        )
    @extend_schema(
        summary="Initialize participant's split payment",
        description="""
        Initiates a Paystack transaction for this participant's share.
        Returns a checkout_url — open it in a popup or redirect.
        After paying, call POST /payments/complete/ with the reference.
                """,
                responses={
                    200: OpenApiResponse(description="Checkout URL returned"),
                    400: OpenApiResponse(description="Already paid or expired"),
                    404: OpenApiResponse(description="Invalid token"),
                },
            )
    def post(self, request, pay_token):
        from transactions.models import SplitParticipant
        from payments.services.factory import get_gateway

        try:
            participant = SplitParticipant.objects.select_related(
                "split_order__order__event"
            ).get(pay_token=pay_token, user=request.user)
        except SplitParticipant.DoesNotExist:
            return api_response(message="Invalid or expired payment link.", status_code=404)

        if participant.split_order.is_expired():
            return api_response(message="This split payment has expired.", status_code=400)

        if participant.status == "paid":
            return api_response(message="You have already paid.", status_code=400)

        gateway   = get_gateway("NG")
        reference = f"qavtix_split_{participant.id.hex[:16]}"

        participant.payment_reference = reference
        participant.save(update_fields=["payment_reference"])

        try:
            init = gateway.initialize_transaction(
                email=request.user.email,
                amount_kobo=int(participant.amount * 100),
                currency="NGN",
                reference=reference,
                metadata={
                    "flow":           "split_participant",
                    "participant_id": str(participant.id),
                    "split_order_id": str(participant.split_order.id),
                    "order_id":       str(participant.split_order.order.id),
                },
            )
        except Exception as e:
            return api_response(message=f"Failed to initialize payment: {str(e)}", status_code=500)

        return api_response(
            message="Proceed to payment.",
            status_code=200,
            data={
                "reference":    reference,
                "checkout_url": init["checkout_url"],
                "amount":       init["amount_kobo"],
            },
        )


@extend_schema(
    request=AddCardSerializer,
    responses={
        201: PaymentCardSerializer,
        400: None,
        500: None
    },
    description="Add a new payment card for the authenticated user. Handles Stripe errors and prevents duplicate cards."
)
class AddCardView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = AddCardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        country = serializer.validated_data["country"]
        payment_method_id = serializer.validated_data["payment_method_id"]
        set_default = serializer.validated_data["set_default"]

        gateway = get_gateway(country)

        try:
            card = gateway.add_card(
                user=user,
                payment_method_id=payment_method_id,
                email=user.email,
            )
        except InvalidRequestError as e:
            # Stripe says the payment method doesn't exist
            return api_response(
                message="Invalid payment method. Please check your card details and try again.",
                status_code=400,
                data={}
            )
        except StripeError as e:
            # Catch any other Stripe-related errors
            return api_response(
                message=f"Payment service error: {e.user_message or str(e)}",
                status_code=400,
                data={}
            )
        except Exception as e:
            # Catch anything else
            return api_response(
                message="An unexpected error occurred while adding your card. Please try again later.",
                status_code=500,
                data={}
            )
        existing_card = PaymentCard.objects.filter(
            user=user,
            last4=card.last4,
            exp_month=card.exp_month,
            exp_year=card.exp_year,
            brand=card.brand,
            provider=card.provider
        ).first()

        if existing_card:
            return api_response(
                message=f"You already have this card: ****{existing_card.last4} ({existing_card.brand})",
                status_code=400,
                data={}
            )

        # Set default if needed
        if set_default or not PaymentCard.objects.filter(user=user).exists():
            PaymentCard.objects.filter(user=user).update(is_default=False)
            card.is_default = True
        else:
            card.is_default = False

        card.save()

        return api_response(
            message="Card added successfully",
            status_code=201,
            data=PaymentCardSerializer(card).data
        )



@extend_schema(
    responses={200: PaymentCardSerializer(many=True)},
    description="Retrieve all payment cards for the authenticated user."
)
class ListCardsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cards = PaymentCard.objects.filter(user=request.user)
        return Response(PaymentCardSerializer(cards, many=True).data)
    
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        serializer = self.get_serializer(queryset, many=True)

        return api_response(
            message="cards retrieved successfully",
            status_code=200,
            data=serializer.data
        )


@extend_schema(
    request=SetDefaultCardRequestSerializer,
    responses={200: SetDefaultCardResponseSerializer, 400: None, 404: None},
    description="Set a specific payment card as the default for the user."
)
class SetDefaultCardView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        card_id = request.data.get("card_id")
        if not card_id:
            return Response({"error": "card_id is required"}, status=400)

        try:
            card = PaymentCard.objects.get(id=card_id, user=request.user)
        except PaymentCard.DoesNotExist:
            return Response({"error": "Card not found"}, status=404)

        PaymentCard.objects.filter(user=request.user).update(is_default=False)
        card.is_default = True
        card.save()

        return api_response(
            message="card default successfully",
            status_code=200,
            data=card.id
        )



@extend_schema(
    description="Delete a payment card for the authenticated user. If the deleted card was default, the next card becomes default.",
    request=inline_serializer(
        name="DeleteCardRequest",
        fields={
            "card_id": serializers.UUIDField(),
        }
    ),
    responses=inline_serializer(
        name="DeleteCardResponse",
        fields={
            "status": serializers.CharField()
        }
    )
)
class DeleteCardView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        card_id = request.data.get("card_id")
        if not card_id:
            return Response({"error": "card_id is required"}, status=400)

        try:
            card = PaymentCard.objects.get(id=card_id, user=request.user)
        except PaymentCard.DoesNotExist:
            return Response({"error": "Card not found"}, status=404)

        was_default = card.is_default
        card.delete()

        if was_default:
            next_card = PaymentCard.objects.filter(user=request.user).first()
            if next_card:
                next_card.is_default = True
                next_card.save()

        return Response({"status": "deleted"})
