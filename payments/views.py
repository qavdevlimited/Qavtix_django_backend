# payments/views.py
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from payments.services.add_card_service import AddCardConfirmService, AddCardInitiateService
from payments.services.card_checkout_service import CardCheckoutService
from payments.services.card_service import CardError, CardListService, DeleteCardService, SetDefaultCardService
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
    
    

class AddCardInitiateView(APIView):
    """
    POST /payments/cards/initiate/

    Initializes a small ₦50 Paystack charge to tokenize the card.
    Returns a checkout_url — open in Paystack popup.
    After user pays, call POST /payments/cards/confirm/ with the reference.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Initiate add card",
        description=(
            "Creates a ₦50 Paystack verification charge. "
            "Open the returned checkout_url in a Paystack popup. "
            "The ₦50 is automatically refunded after the card is saved."
        ),
        request=AddCardInitiateSerializer,
        responses={200: OpenApiResponse(description="Checkout URL returned")},
        examples=[
            OpenApiExample(
                "Initiate add card",
                value={"country": "NG", "currency": "NGN"},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = AddCardInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = AddCardInitiateService(
                user=request.user,
                country=data.get("country", "NG"),
                currency=data.get("currency", "NGN"),
            ).run()
        except Exception as e:
            return api_response(message=str(e), status_code=500)

        return api_response(
            message="Open the checkout URL to add your card.",
            status_code=200,
            data=result,
        )


class AddCardConfirmView(APIView):
    """
    POST /payments/cards/confirm/

    Verifies the Paystack transaction, saves the card, refunds the ₦50.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Confirm add card",
        description=(
            "Verifies the Paystack transaction after popup completes. "
            "Saves the card and automatically refunds the ₦50 verification charge."
        ),
        request=AddCardConfirmSerializer,
        responses={
            200: OpenApiResponse(description="Card saved successfully"),
            402: OpenApiResponse(description="Payment verification failed"),
        },
        examples=[
            OpenApiExample(
                "Confirm add card",
                value={
                    "reference":   "qavtix_addcard_abc123def456",
                    "country":     "NG",
                    "set_default": True,
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = AddCardConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = AddCardConfirmService(
                user=request.user,
                reference=data["reference"],
                country=data.get("country", "NG"),
                set_default=data.get("set_default", True),
            ).run()
        except Exception as e:
            return api_response(message=str(e), status_code=402)

        return api_response(
            message="Card added successfully." if result["is_new"] else "Card already saved.",
            status_code=200,
            data=result,
        )


class CardListView(APIView):
    """
    GET /payments/cards/

    Returns all saved payment cards for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="List saved cards",
        description="Returns all saved payment cards ordered by default first.",
        responses={200: OpenApiResponse(description="Cards returned")},
    )
    def get(self, request):
        cards = CardListService(user=request.user).run()
        return api_response(
            message="Cards retrieved.",
            status_code=200,
            data=cards,
        )


class SetDefaultCardView(APIView):
    """
    POST /payments/cards/<card_id>/default/

    Sets a saved card as the default payment method.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Set default card",
        description="Sets the specified card as default. Unsets all others.",
        responses={
            200: OpenApiResponse(description="Default card updated"),
            404: OpenApiResponse(description="Card not found"),
        },
    )
    def post(self, request, card_id):
        try:
            result = SetDefaultCardService(
                user=request.user,
                card_id=card_id,
            ).run()
        except CardError as e:
            return api_response(message=e.message, status_code=e.status)

        return api_response(
            message="Default card updated.",
            status_code=200,
            data=result,
        )


class DeleteCardView(APIView):
    """
    DELETE /payments/cards/<card_id>/

    Deletes a saved card. If it was the default, the next card becomes default.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Delete card",
        description=(
            "Permanently deletes a saved card. "
            "If deleted card was the default, the next available card is set as default."
        ),
        responses={
            200: OpenApiResponse(description="Card deleted"),
            404: OpenApiResponse(description="Card not found"),
        },
    )
    def delete(self, request, card_id):
        try:
            result = DeleteCardService(
                user=request.user,
                card_id=card_id,
            ).run()
        except CardError as e:
            return api_response(message=e.message, status_code=e.status)

        return api_response(
            message="Card deleted.",
            status_code=200,
            data=result,
        )



class CardCheckoutView(APIView):
    """
    POST /payments/charge-card/
 
    Charges a saved card directly — no Paystack popup needed.
    Tickets are issued immediately in the same request.
 
    Supports:
      - Normal event ticket purchase
      - Marketplace listing purchase
    """
    permission_classes = [IsAuthenticated]
 
    @extend_schema(
        summary="Pay with saved card",
        description=(
            "Charges a previously saved card directly using Paystack charge_authorization. "
            "No popup or redirect needed. Tickets are issued immediately on success. "
            "Supports both normal event purchases and marketplace listings."
        ),
        request=CardCheckoutSerializer,
        responses={
            200: OpenApiResponse(description="Payment successful, tickets issued"),
            400: OpenApiResponse(description="Validation error"),
            402: OpenApiResponse(description="Card charge failed"),
            404: OpenApiResponse(description="Card or event not found"),
        },
        examples=[
            OpenApiExample(
                "Normal purchase with saved card",
                value={
                    "country":      "NG",
                    "currency":     "NGN",
                    "full_name":    "John Doe",
                    "phone_number": "08012345678",
                    "card_id":      "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "event_id":     "7b20504d-6226-4587-b7c8-686520550150",
                    "tickets":      [{"ticket_id": 1, "quantity": 2}],
                    "promo_code":   "",
                    "affiliate_code": None,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Marketplace purchase with saved card",
                value={
                    "country":                "NG",
                    "currency":               "NGN",
                    "full_name":              "John Doe",
                    "phone_number":           "08012345678",
                    "card_id":                "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "marketplace_listing_id": 5,
                },
                request_only=True,
            ),
        ],
    )
    @transaction.atomic
    def post(self, request):
        serializer = CardCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
 
        try:
            result = CardCheckoutService(
                user=request.user,
                data=data,
            ).run()
        except CheckoutError as e:
            transaction.set_rollback(True)
            return api_response(message=e.message, status_code=e.status)
        except Exception as e:
            transaction.set_rollback(True)
            return api_response(message=f"Charge failed: {str(e)}", status_code=500)
 
        return api_response(
            message="Payment successful. Tickets issued.",
            status_code=200,
            data=result,
        )
 