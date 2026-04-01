# marketplace/serializers.py
from rest_framework import serializers
from marketplace.models import MarketListing
from events.models import EventLocation, EventMedia
from django.db.models import Sum
from transactions.models import IssuedTicket
from host.serializers import EventLocationNestedSerializer,OrganizerSocialLinkNestedSerializer,EventMediaNestedSerializer,EventDetailsSerializer
from public.serializers import EventLocationSerializer
from django.utils import timezone
from decimal import Decimal

class MarketListingSerializer(serializers.ModelSerializer):
    event_name = serializers.CharField(source="ticket.event.title", read_only=True)
    host = serializers.CharField(source="ticket.event.host.full_name", read_only=True)
    category = serializers.CharField(source="ticket.event.category.name", read_only=True)
    event_datetime = serializers.DateTimeField(source="ticket.event.start_datetime", read_only=True)
    event_description = serializers.CharField(source="ticket.event.short_description", read_only=True)
    
    event_location = serializers.SerializerMethodField()
    event_image = serializers.SerializerMethodField()
    attendees_count = serializers.SerializerMethodField()

    is_mine = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()

    class Meta:
        model = MarketListing
        fields = [
            "id",
            "event_name",
            "host",
            "price",
            "category",
            "event_datetime",
            "event_location",
            "event_image",
            "attendees_count",
            "status",
            "created_at",
            "expires_at",
            "is_mine",
            "is_favorite",
            'event_description',
        ]

    def get_is_mine(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        # Compare logged-in user with the ticket seller
        return obj.seller == request.user
    
    def get_event_location(self, obj):
        location = getattr(obj.ticket.event, "event_location", None)
        if location:
            return EventLocationSerializer(location).data
        return None

    def get_event_image(self, obj):
        featured = obj.ticket.event.media.filter(is_featured=True).first()
        if featured:
            return featured.image_url
        first_media = obj.ticket.event.media.first()
        return first_media.image_url if first_media else None

    def get_attendees_count(self, obj):
        return IssuedTicket.objects.filter(
            event=obj.ticket.event
        ).exclude(status="cancelled").values('owner').distinct().count()
    
    def get_is_favorite(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        # Check if the logged-in user has favorited this event
        return obj.ticket.event.favorited_by.filter(user=request.user).exists()
    


class MarketListingCreateSerializer(serializers.Serializer):
    ticket_id = serializers.IntegerField()
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    expires_at = serializers.DateTimeField(required=False)

    def validate_expires_at(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("Expiry time must be in the future.")
        return value
    



class MarketEventDetailsSerializer(EventDetailsSerializer):
    resale_price = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()
    listing_id = serializers.SerializerMethodField()
    listing_status = serializers.SerializerMethodField()

   
    tickets = serializers.SerializerMethodField()

    class Meta(EventDetailsSerializer.Meta):
        fields = EventDetailsSerializer.Meta.fields + [
            "resale_price",
            "seller_name",
            "expires_at",
            "listing_id",
            "listing_status",
        ]

    def _get_listing(self):
        return self.context.get("listing")

    def get_resale_price(self, obj):
        listing = self._get_listing()
        return str(listing.price) if listing else None

    def get_seller_name(self, obj):
        listing = self._get_listing()
        return listing.seller.attendee_profile.full_name if listing else None

    def get_expires_at(self, obj):
        listing = self._get_listing()
        return listing.expires_at if listing else None

    def get_listing_id(self, obj):
        listing = self._get_listing()
        return listing.id if listing else None

    def get_listing_status(self, obj):
        listing = self._get_listing()
        return listing.status if listing else None

    def get_tickets(self, obj):
        listing = self._get_listing()
        if not listing:
            return None

        original_ticket = listing.ticket.order_ticket.ticket

        return {
            "ticket_type": original_ticket.ticket_type,
            "description": original_ticket.description,
            "price": str(listing.price),
            "quantity": 1,
            "per_person_max": 1,
            "sales_start": original_ticket.sales_start,
            "sales_end": original_ticket.sales_end,
            "promo_codes": [],
        }