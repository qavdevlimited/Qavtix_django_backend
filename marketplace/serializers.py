# marketplace/serializers.py
from rest_framework import serializers
from marketplace.models import MarketListing
from events.models import Event, EventLocation, EventMedia, Tag
from django.db.models import Sum
from public.models import Follow
from transactions.models import IssuedTicket
from host.serializers import EventLocationNestedSerializer,OrganizerSocialLinkNestedSerializer,EventMediaNestedSerializer,EventDetailsSerializer, TicketNestedSerializer
from public.serializers import EventLocationSerializer
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta

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
    marketplace_id = serializers.CharField(source='id')
    id = serializers.CharField(source='ticket.event.id', read_only=True)

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
            'marketplace_id',
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
    



class MarketEventDetailsSerializer(serializers.ModelSerializer):
    # Singular ticket
    ticket = serializers.SerializerMethodField()
    
    # Include any other fields you need
    resale_price = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()
    listing_id = serializers.SerializerMethodField()
    listing_status = serializers.SerializerMethodField()
    event_location = EventLocationNestedSerializer(required=True)
    social_links = OrganizerSocialLinkNestedSerializer(many=True, required=False)
    tags = serializers.SlugRelatedField(slug_field='name', queryset=Tag.objects.all(), many=True)
    event_image = EventMediaNestedSerializer(many=True, required=False)
    attendees_count = serializers.SerializerMethodField()
    event_status = serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()
    category = serializers.CharField(source="category.name", read_only=True)
    is_following = serializers.SerializerMethodField()
    is_trending = serializers.SerializerMethodField()
    is_filling_fast = serializers.SerializerMethodField()
    organizer_id = serializers.IntegerField(source='host.id')
    event_media = EventMediaNestedSerializer(many=True, read_only=True, source="media")

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'category', 'tags', 'event_type', 'start_datetime', 'end_datetime',
            'location_type', 'short_description', 'full_description',
            'organizer_display_name', 'organizer_description', 'public_email', 'phone_number',
            'event_location', 'social_links', 'ticket', 'event_status', 'event_image', 'attendees_count',
            'age_restriction','is_favorite','is_following','is_trending','is_filling_fast','organizer_id',
            'currency','event_media',
            "resale_price", "seller_name", "expires_at", "listing_id", "listing_status"
        ]

    def _get_listing(self):
        return self.context.get("listing")

    # Single ticket
    def get_ticket(self, obj):
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

    # Other methods for resale_price, seller_name, etc.
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
    

    def get_attendees_count(self, obj):
        """
        Count unique users who purchased any ticket for this event.
        Only count completed orders.
        """
        return (
            obj.order_set
            .filter(status="completed")   # Only completed orders
            .values("user")               # Group by user
            .distinct()                   # Unique users
            .count()                      # Count of unique attendees
        )
    
    def get_is_favorite(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        # Check if the logged-in user has favorited this event
        return obj.favorited_by.filter(user=request.user).exists()

    
    def get_is_following(self, obj):
        request = self.context.get("request")

        if request and request.user.is_authenticated:
            return Follow.objects.filter(
                user=request.user,
                host=obj.host
            ).exists()

        return False
    
    def get_ticket(self, obj):
        listing = self.context.get("listing")
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
        
        

    def get_total_sold(self, obj):
        return obj.tickets.aggregate(
            total_sold=Sum("sold_count")
        )["total_sold"] or 0

    def get_total_capacity(self, obj):
        return obj.tickets.aggregate(
            total=Sum("quantity")
        )["total"] or 0

    def get_is_trending(self, obj):
        total_sold = self.get_total_sold(obj)
        return total_sold >= 1000
    
    def get_is_filling_fast(self, obj):
        total_sold = self.get_total_sold(obj)
        total_capacity = self.get_total_capacity(obj)

        if total_capacity == 0:
            return False

        fill_percentage = (total_sold / total_capacity) * 100

        return fill_percentage >= 70 

    # Replace get_event_status:
    def get_event_status(self, obj):
        tickets = getattr(obj, "all_tickets", None) or list(obj.tickets.all())
        total_quantity = sum(t.quantity for t in tickets)
        sold_quantity  = sum(getattr(t, "sold_count", 0) for t in tickets)

        if sold_quantity >= total_quantity:
            return "sold-out"
        elif total_quantity > 0 and sold_quantity / total_quantity >= 0.75:
            return "fast-selling"
        elif obj.created_at >= timezone.now() - timedelta(days=7):
            return "new"
        return "normal"