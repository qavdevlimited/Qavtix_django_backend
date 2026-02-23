# serializers.py

from rest_framework import serializers
from transactions.models import IssuedTicket
from rest_framework import serializers
from .models import FavoriteEvent
from rest_framework import serializers
from events.models import Event
from public.serializers import EventLocationSerializer
from django.utils import timezone
from datetime import timedelta

class TicketDashboardSerializer(serializers.ModelSerializer):
    sn = serializers.SerializerMethodField()

    event_name = serializers.CharField(source="event.title", read_only=True)
    category = serializers.CharField(source="event.category.name", read_only=True)

    payment = serializers.CharField(source="order.get_status_display", read_only=True)
    event_status = serializers.CharField(source="event.status", read_only=True)

    event_datetime = serializers.DateTimeField(
        source="event.start_datetime",
        read_only=True
    )

    event_image = serializers.SerializerMethodField()

    ticket_type = serializers.CharField(source="ticket_type.name", read_only=True)
    ticket_id = serializers.CharField(read_only=True)
    ticket_status = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = IssuedTicket
        fields = [
            "sn",
            "id",
            "ticket_id",
            "event_name",
            "event_image",
            "category",
            "payment",
            "event_status",
            "ticket_status",
            "ticket_type",
            "event_datetime",
        ]

    def get_sn(self, obj):
        view = self.context.get("view")

        if view and hasattr(view, "paginator"):
            page = view.paginator.page
            index = list(page.object_list).index(obj)
            return (page.number - 1) * view.paginator.page_size + index + 1

        return 1

    def get_event_image(self, obj):
        featured_media = obj.event.media.filter(is_featured=True).first()

        if featured_media:
            return featured_media.image_url

        first_media = obj.event.media.first()
        return first_media.image_url if first_media else None
    




class FavoriteEventSerializer(serializers.ModelSerializer):
    location = EventLocationSerializer(read_only=True)
    media = serializers.SerializerMethodField()
    business_name = serializers.SerializerMethodField()
    dynamic_status = serializers.SerializerMethodField()
    attendees_count = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            "id", "title", "category", "start_datetime", "end_datetime",
            "location", "media", "business_name", "dynamic_status", "attendees_count"
        ]
    
    def get_category(self, obj):
        return obj.category.name if obj.category else None

    def get_media(self, obj):
        return [
            {"image_url": m.image_url, "video_url": m.video_url, "is_featured": m.is_featured}
            for m in obj.media.all()
        ]

    def get_business_name(self, obj):
        return getattr(obj.host, "business_name", None)

    def get_dynamic_status(self, obj):
        total_quantity = sum(t.quantity for t in obj.tickets.all())
        sold_quantity = sum(getattr(t, "sold_count", 0) for t in obj.tickets.all())

        if sold_quantity >= total_quantity:
            return "sold-out"
        elif total_quantity > 0 and sold_quantity / total_quantity >= 0.75:
            return "fast-selling"
        elif obj.created_at >= timezone.now() - timedelta(days=7):
            return "new"
        return "normal"

    def get_attendees_count(self, obj):
        return obj.order_set.filter(status="completed").values("user").distinct().count()