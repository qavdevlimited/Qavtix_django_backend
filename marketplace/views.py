# marketplace/views.py
from rest_framework import generics, permissions, filters, status
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from marketplace.filter import MarketListingFilter
from marketplace.models import MarketListing
from marketplace.services import MarketplaceListingService,MarketplaceListingError
from transactions.models import IssuedTicket
from .serializers import MarketListingSerializer,MarketEventDetailsSerializer,MarketListingCreateSerializer
from public.response import api_response


class MarketListingCreateView(generics.CreateAPIView):
    serializer_class = MarketListingCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        ticket_id = request.data.get("ticket_id")
        price = request.data.get("price")
        expires_at = request.data.get("expires_at")

       
        try:
            ticket = (
                request.user.owned_tickets
                .select_related("event", "event__host")  # prevents future queries
                .get(id=ticket_id, status="active")
            )
        except IssuedTicket.DoesNotExist:
            return api_response(
                message="Ticket not found or not owned.",
                status_code=400
            )

        # Call service
        try:
            listing = MarketplaceListingService.create_listing(
                user=request.user,
                ticket=ticket,
                price=price,
                expires_at=expires_at
            )
        except MarketplaceListingError as e:
            return api_response(
                message=e.message,
                status_code=e.status
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
    search_fields = ["ticket__event__title", "ticket__event__host__full_name"]
    filterset_class = MarketListingFilter
    pagination_class = generics.ListAPIView.pagination_class  # default DRF pagination

    def get_queryset(self):
        queryset = MarketListing.objects.filter(status="active")
        return queryset.order_by("price")

    def get_filterset_kwargs(self, filterset_class):
        """Pass request to filterset"""
        kwargs = super().get_filterset_kwargs(filterset_class)
        kwargs['request'] = self.request
        return kwargs
    
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
    queryset = MarketListing.objects.all()

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
    


class MarketListingDetailView(generics.RetrieveAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = MarketEventDetailsSerializer

    def get_queryset(self):
        return (
            MarketListing.objects
            .filter(status="active")
            .select_related(
                "ticket",
                "ticket__event",
                "ticket__order_ticket",
                "ticket__order_ticket__ticket",
                "seller",
            )
            .prefetch_related(
                "ticket__event__media",
                "ticket__event__tickets",
                "ticket__event__tags",
                "ticket__event__social_links",
            )
        )

    def retrieve(self, request, *args, **kwargs):
        listing = self.get_object()

        # Optional: prevent expired listing access
        if listing.expires_at and listing.expires_at < timezone.now():
            return api_response(
                message="This listing has expired",
                status_code=404,
                data=None
            )

        event = listing.ticket.event  # clean access

        serializer = MarketEventDetailsSerializer(
            event,
            context={
                "request": request,
                "listing": listing,
            }
        )

        return api_response(
            message="Marketplace listing retrieved successfully",
            status_code=200,
            data=serializer.data,
        )