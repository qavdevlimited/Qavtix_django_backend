# marketplace/serializers.py
from rest_framework import serializers
from marketplace.models import MarketListing
from events.models import EventLocation, EventMedia
from django.db.models import Sum
from transactions.models import IssuedTicket

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