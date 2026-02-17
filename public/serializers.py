from rest_framework import serializers
from events.models import Event, EventLocation, Ticket
from host.models import Host
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count


class EventLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventLocation
        fields = ["venue_name", "address", "city", "state", "country"]

class EventListSerializer(serializers.ModelSerializer):
    location = EventLocationSerializer(read_only=True)
    media = serializers.SerializerMethodField()
    business_name = serializers.SerializerMethodField()
    dynamic_status = serializers.SerializerMethodField()
    attendees_count = serializers.SerializerMethodField()
    category=serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id", "title", "category", "start_datetime", "end_datetime",
            "location", "media", "business_name", "dynamic_status", "attendees_count"
        ]
    
    def get_category(self,obj):
        return obj.category.name

    def get_media(self, obj):
        return [{"image_url": m.image_url, "video_url": m.video_url,"is_featured":m.is_featured} for m in obj.media.all()]

    def get_business_name(self, obj):
        if hasattr(obj.host, "business_name"):
            return obj.host.business_name
        return None

    def get_dynamic_status(self, obj):
        """
        Compute status based on tickets left and creation date.
        - sold-out: all tickets sold
        - fast-selling: less than 25% left
        - new: created within last 7 days
        - otherwise: normal
        """
        total_quantity = sum(t.quantity for t in obj.tickets.all())
        sold_quantity = sum(getattr(t, "sold_quantity", 0) for t in obj.tickets.all())

        if sold_quantity >= total_quantity:
            return "sold-out"
        elif total_quantity > 0 and sold_quantity / total_quantity >= 0.75:
            return "fast-selling"
        elif obj.created_at >= timezone.now() - timedelta(days=7):
            return "new"
        return "normal"

    
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



class TrendingHostSerializer(serializers.ModelSerializer):
    events_count = serializers.IntegerField()
    trending_score = serializers.FloatField()

    class Meta:
        model = Host
        fields = ["id", "business_name", "followers", "events_count", "trending_score"]



        