# payments/views.py
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from payments.services.factory import get_gateway
from payments.models import PaymentCard, Payment
from payments.serializers import CheckoutPaymentSerializer, AddCardSerializer, PaymentCardSerializer
from payments.services.checkout_service import CheckoutService, CheckoutError
from drf_yasg.utils import swagger_auto_schema
from decimal import Decimal
from django.utils import timezone
from public.response import flatten_errors,api_response


class CheckoutPaymentView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        request_body=CheckoutPaymentSerializer,
        responses={200: "Payment response"},
    )
    @transaction.atomic
    def post(self, request):
        serializer = CheckoutPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user if request.user.is_authenticated else None
        email = user.email if user else data.get("email")

        if not email:
            return Response(
                {"error": "email is required for guest checkout"}, status=400
            )

        try:
            result = CheckoutService(user=user, email=email, data=data).run()
        except CheckoutError as e:
            transaction.set_rollback(True)
            return api_response(message=e.message,status_code=500)
        except Exception as e:
            transaction.set_rollback(True)
            return api_response(message=f"Payment failed: {str(e)}",status_code=500)

        payment = result["payment"]
        order = result["order"]
        card = result["card"]
        card_is_temporary = result["card_is_temporary"]

        return api_response(
            message="Your Ticket will be sent after confirmation of your Payment",
            status_code=200,
            data={
                "payment_id": payment.id,
                "order_id": order.id,
                "status": payment.status,
                "subtotal": str(result["subtotal"]),
                "discount": str(result["discount"]),
                "total_amount": str(result["total_amount"]),
                "currency": data["currency"],
                "card": {
                    "id": card.id if not card_is_temporary else None,
                    "provider": card.provider,
                    "brand": card.brand,
                    "last4": card.last4,
                    "exp_month": card.exp_month,
                    "exp_year": card.exp_year,
                    "is_default": card.is_default,
                },
            },
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
        card = gateway.add_card(
            user=user,
            payment_method_id=payment_method_id,
            email=user.email,
        )

        if set_default or not PaymentCard.objects.filter(user=user).exists():
            PaymentCard.objects.filter(user=user).update(is_default=False)
            card.is_default = True
        else:
            card.is_default = False

        card.save()

        return Response(PaymentCardSerializer(card).data, status=201)


class ListCardsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        cards = PaymentCard.objects.filter(user=request.user)
        return Response(PaymentCardSerializer(cards, many=True).data)


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

        return Response({"status": "success", "default_card": card.id})


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
