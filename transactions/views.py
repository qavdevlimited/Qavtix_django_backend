# payments/views/featured_views.py
import logging
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db import transaction
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

from transactions.serializers import (
    FeaturedInitiateSerializer,
    CompleteFeaturedSerializer,
)
from transactions.services.featured_service import (
    FeaturedInitiateService,
    CompleteFeaturedService,
    FeaturedError,
)
from public.response import api_response

logger = logging.getLogger(__name__)


class FeaturedPlanListView(APIView):
    """
    GET /payments/featured/plans/
    Returns all active featured plans. Public.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="List featured plans",
        description="Returns all available featured event pricing plans.",
        responses={200: OpenApiResponse(description="Plans returned")},
    )
    def get(self, request):
        from transactions.models import FeaturedPlan

        plans = FeaturedPlan.objects.filter(is_active=True).values(
            "slug", "name", "duration_days",
            "price", "original_price", "features",
        )

        return api_response(
            message="Featured plans retrieved.",
            status_code=200,
            data=list(plans),
        )


class FeaturedInitiateView(APIView):
    """
    POST /payments/featured/initiate/

    Initiates featured event payment.

    With card_id:    charges saved card directly → activates immediately
    Without card_id: returns checkout_url → FE opens popup → call /complete/
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Initiate featured event payment",
        description=(
            "Start the process of featuring an event. "
            "With card_id: charges immediately, no popup needed. "
            "Without card_id: returns checkout_url for Paystack popup."
        ),
        request=FeaturedInitiateSerializer,
        responses={
            200: OpenApiResponse(description="Payment initiated or feature activated"),
            400: OpenApiResponse(description="Already featured or validation error"),
            402: OpenApiResponse(description="Card charge failed"),
            403: OpenApiResponse(description="Not your event"),
            404: OpenApiResponse(description="Event or plan not found"),
        },
        examples=[
            OpenApiExample(
                "Popup flow",
                value={
                    "event_id":  "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "plan_slug": "standard",
                    "country":   "NG",
                    "currency":  "NGN",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Saved card flow",
                value={
                    "event_id":  "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "plan_slug": "advanced",
                    "country":   "NG",
                    "currency":  "NGN",
                    "card_id":   "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                },
                request_only=True,
            ),
        ],
    )
    @transaction.atomic
    def post(self, request):
        serializer = FeaturedInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = FeaturedInitiateService(
                user=request.user,
                data=serializer.validated_data,
            ).run()
        except FeaturedError as e:
            transaction.set_rollback(True)
            return api_response(message=e.message, status_code=e.status)
        except Exception as e:
            transaction.set_rollback(True)
            return api_response(message=f"Failed: {str(e)}", status_code=500)

        msg = "Feature activated." if result.get("status") == "active" else "Proceed to payment."
        return api_response(message=msg, status_code=200, data=result)


class CompleteFeaturedView(APIView):
    """
    POST /payments/featured/complete/

    Called after Paystack popup completes.
    Not needed if card_id was used — that flow handles everything in initiate.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Complete featured event payment",
        description=(
            "Call after Paystack popup completes. "
            "Verifies payment, activates featured plan, sends confirmation email."
        ),
        request=CompleteFeaturedSerializer,
        responses={
            200: OpenApiResponse(description="Feature activated"),
            402: OpenApiResponse(description="Payment verification failed"),
            404: OpenApiResponse(description="Featured record not found"),
        },
        examples=[
            OpenApiExample(
                "Complete featured",
                value={
                    "reference": "qavtix_feat_abc123",
                    "save_card": True,
                    "country":   "NG",
                },
                request_only=True,
            )
        ],
    )
    @transaction.atomic
    def post(self, request):
        serializer = CompleteFeaturedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = CompleteFeaturedService(
                user=request.user,
                reference=data["reference"],
                save_card=data.get("save_card", False),
                country=data.get("country", "NG"),
            ).run()
        except FeaturedError as e:
            transaction.set_rollback(True)
            return api_response(message=e.message, status_code=e.status)
        except Exception as e:
            transaction.set_rollback(True)
            return api_response(message=f"Completion failed: {str(e)}", status_code=500)

        return api_response(
            message="Your event is now featured!",
            status_code=200,
            data=result,
        )