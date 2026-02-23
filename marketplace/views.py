# marketplace/views.py
from rest_framework import generics, permissions, filters, status
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from marketplace.models import MarketListing
from .serializers import MarketListingSerializer
from public.response import api_response


class MarketListingCreateView(generics.CreateAPIView):
    serializer_class = MarketListingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        ticket_id = request.data.get("ticket_id")
        price = request.data.get("price")
        expires_at = request.data.get("expires_at")  # optional

        # Validate ticket ownership
        try:
            ticket = request.user.owned_tickets.get(id=ticket_id, status="active")
        except MarketListing.ticket.model.DoesNotExist:
            return api_response(
                message="Ticket not found or not owned.",
                status_code=400
            )

        # Prevent double listing
        if hasattr(ticket, "market_listing") and ticket.market_listing.status == "active":
            return api_response(
                message="Ticket is already listed in the marketplace.",
                status_code=400
            )

        listing = MarketListing.objects.create(
            ticket=ticket,
            seller=request.user,
            price=price,
            expires_at=expires_at
        )

        serializer = self.get_serializer(listing)
        return api_response(
            message="Ticket Listed in Marketplace",
            status_code=201,
            data=serializer.data
        )


class MarketListingListView(generics.ListAPIView):
    serializer_class = MarketListingSerializer
    permission_classes = [permissions.AllowAny]  # public listings
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    search_fields = ["ticket__event__title", "ticket__event__host__name"]
    filterset_fields = {
        "ticket__event__category__id": ["exact"],
        "price": ["gte", "lte"],
        "ticket__event__start_datetime": ["gte", "lte"],
    }
    pagination_class = generics.ListAPIView.pagination_class  # default DRF pagination

    def get_queryset(self):
        queryset = MarketListing.objects.filter(status="active")
        return queryset.order_by("price")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated_response = self.get_paginated_response(serializer.data)
            paginated_response.data = {
                "message": "Marketplace Listings retrieved successfully",
                "status_code": 200,
                "data": paginated_response.data,
            }
            return paginated_response

        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="Marketplace Listings retrieved successfully",
            status_code=200,
            data=serializer.data,
        )


class MarketListingDeleteView(generics.DestroyAPIView):
    serializer_class = MarketListingSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        listing_id = self.kwargs.get("pk")
        try:
            listing = MarketListing.objects.get(id=listing_id, seller=self.request.user)
        except MarketListing.DoesNotExist:
            return None
        return listing

    def delete(self, request, *args, **kwargs):
        listing = self.get_object()
        if not listing:
            return api_response(message="Listing not found.", status_code=404)

        listing.status = "cancelled"
        listing.save()

        serializer = self.get_serializer(listing)
        return api_response(
            message="Successfully removed ticket from marketplace",
            status_code=200,
            data=serializer.data
        )