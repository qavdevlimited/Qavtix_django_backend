# marketplace/serializers.py
from rest_framework import serializers
from marketplace.models import MarketListing
from events.models import EventLocation, EventMedia
from django.db.models import Sum
from transactions.models import IssuedTicket
from host.serializers import EventLocationNestedSerializer,OrganizerSocialLinkNestedSerializer,EventMediaNestedSerializer,EventDetailsSerializer

class MarketListingSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="ticket.event.title", read_only=True)
    host_name = serializers.CharField(source="ticket.event.host.name", read_only=True)
    price = serializers.DecimalField(source="ticket.price", max_digits=12, decimal_places=2, read_only=True)
    category = serializers.CharField(source="ticket.event.category.name", read_only=True)
    event_datetime = serializers.DateTimeField(source="ticket.event.start_datetime", read_only=True)
    
    venue = serializers.SerializerMethodField()
    featured_image = serializers.SerializerMethodField()
    unique_buyers_count = serializers.SerializerMethodField()

    is_mine = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()

    class Meta:
        model = MarketListing
        fields = [
            "id",
            "event_title",
            "host_name",
            "price",
            "category",
            "event_datetime",
            "venue",
            "featured_image",
            "unique_buyers_count",
            "status",
            "created_at",
            "expires_at",
            "is_mine",
            "is_favorite",
        ]

    def get_is_mine(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        # Compare logged-in user with the ticket seller
        return obj.seller == request.user
    
    def get_venue(self, obj):
        location = getattr(obj.ticket.event, "location", None)
        if location:
            return location.venue_name
        return None

    def get_featured_image(self, obj):
        featured = obj.ticket.event.media.filter(is_featured=True).first()
        if featured:
            return featured.image_url
        first_media = obj.ticket.event.media.first()
        return first_media.image_url if first_media else None

    def get_unique_buyers_count(self, obj):
        return IssuedTicket.objects.filter(
            event=obj.ticket.event
        ).exclude(status="cancelled").values('owner').distinct().count()
    
    def get_is_favorite(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        # Check if the logged-in user has favorited this event
        return obj.ticket.event.favorited_by.filter(user=request.user).exists()
    



class MarketEventDetailsSerializer(EventDetailsSerializer):
    resale_price = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()
    listing_id = serializers.SerializerMethodField()
    listing_status = serializers.SerializerMethodField()

    class Meta(EventDetailsSerializer.Meta):
        fields = EventDetailsSerializer.Meta.fields + [
            "resale_price",
            "seller_name",
            "expires_at",
            "listing_id",
            "listing_status",
        ]

    def get_resale_price(self, obj):
        listing = self.context.get("listing")
        return str(listing.price) if listing else None

    def get_seller_name(self, obj):
        listing = self.context.get("listing")
        return listing.seller.get_full_name() if listing else None

    def get_expires_at(self, obj):
        listing = self.context.get("listing")
        return listing.expires_at if listing else None

    def get_listing_id(self, obj):
        listing = self.context.get("listing")
        return listing.id if listing else None

    def get_listing_status(self, obj):
        listing = self.context.get("listing")
        return listing.status if listing else None

    def to_representation(self, instance):
        """
        instance = Event
        listing is passed via context
        """
        data = super().to_representation(instance)

        listing = self.context.get("listing")
        if not listing:
            return data

        # Get original Ticket model
        original_ticket = listing.ticket.order_ticket.ticket

        # Replace tickets with ONLY resale ticket
        data["tickets"] = [{
            "ticket_type": original_ticket.ticket_type,
            "description": original_ticket.description,
            "price": str(listing.price),  # resale price
            "quantity": 1,
            "per_person_max": 1,
            "sales_start": original_ticket.sales_start,
            "sales_end": original_ticket.sales_end,
            "promo_codes": [],
        }]

        return data