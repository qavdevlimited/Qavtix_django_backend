from rest_framework import serializers
from events.models import Event, EventLocation, Ticket,EventMedia
from host.models import Host
from django.utils import timezone
from datetime import timedelta
from django.db.models import Count

from host.serializers import EventSerializer
from .models import Category, CategorySubscription, Follow, LocationSubscription,Message

from django.db.models import (
    Count, Prefetch, OuterRef, Subquery, Min
)
from transactions.models import Order




class EventLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventLocation
        fields = ["venue_name", "address", "city", "state", "country"]

class EventListSerializer(serializers.ModelSerializer):
    event_location = EventLocationSerializer(read_only=True)
    event_image = serializers.SerializerMethodField()
    host = serializers.SerializerMethodField()
    event_status = serializers.SerializerMethodField()
    attendees_count = serializers.SerializerMethodField()
    category=serializers.SerializerMethodField()
    event_datetime=serializers.DateTimeField(source="start_datetime", read_only=True)
    event_description=serializers.CharField(source="short_description", read_only=True)
    price=serializers.SerializerMethodField()
    event_name=serializers.CharField(source="title", read_only=True)
    is_favorite = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id", "event_name", "category", "event_datetime", "end_datetime",
            "event_location", "event_image", "host", "event_status", "attendees_count","event_description","price","is_favorite"
        ]


    # After — safe
    def get_category(self, obj):
        return obj.category.name if obj.category else None

    # After — safe
    def get_event_location(self, obj):
        location = getattr(obj, "event_location", None)
        if location is None:
            return None
        return EventLocationSerializer(location).data
        
    def get_event_image(self, obj):
        # Uses prefetched featured_media_list instead of hitting DB
        media_list = getattr(obj, "featured_media_list", None)
        if media_list:
            return media_list[0].image_url
        # Fallback — only hits DB if prefetch wasn't applied
        first = obj.media.first()
        return first.image_url if first else None


    # Replace get_price:
    def get_price(self, obj):
        tickets = getattr(obj, "all_tickets", None)
        if tickets:
            prices = [t.price for t in tickets]
            return min(prices) if prices else None
        # Fallback
        lowest = obj.tickets.order_by("price").first()
        return lowest.price if lowest else None


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


    # Replace get_attendees_count:
    def get_attendees_count(self, obj):
        # Use annotated value if available (set by event_list_queryset)
        annotated = getattr(obj, "attendees_count_annotated", None)
        if annotated is not None:
            return annotated
        # Fallback
        return (
            obj.order_set
            .filter(status="completed")
            .values("user")
            .distinct()
            .count()
            )

    def get_host(self, obj):
        host = getattr(obj, "host", None)
        if host is None:
            return None
        return getattr(host, "business_name", None)
    
    def get_is_favorite(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        # Check if the logged-in user has favorited this event
        return obj.favorited_by.filter(user=request.user).exists()



class TrendingHostSerializer(serializers.ModelSerializer):
    events_count = serializers.IntegerField()
    trending_score = serializers.FloatField()

    class Meta:
        model = Host
        fields = ["id", "business_name", "followers", "events_count", "trending_score"]



class FollowActionSerializer(serializers.ModelSerializer):
    host_id = serializers.UUIDField(source="host.id", read_only=True)

    class Meta:
        model = Follow
        fields = ["id", "host_id", "created_at"]  # adjust to your model
        read_only_fields = fields


class HostPublicDetailSerializer(serializers.ModelSerializer):
    followers_count = serializers.IntegerField(read_only=True)
    events_count = serializers.SerializerMethodField()
    upcoming_events = serializers.SerializerMethodField()
    past_events = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    relevant_links=serializers.SerializerMethodField()
    host=serializers.CharField(source="business_name", read_only=True)


    class Meta:
        model = Host
        fields = [
            "id",
            "host",
            "business_type",
            "city",
            "state",
            "country",
            "followers_count",
            "events_count",
            "upcoming_events",
            "past_events",
            "is_following",
            "relevant_links",
            "description",
        ]

    def get_relevant_links(self, obj):
        return obj.relevant_links


    def get_events_count(self, obj):
        return obj.hoster.count()

    def get_upcoming_events(self, obj):
        events = getattr(obj, "upcoming_events_list", None)
        if events is None:
            now = timezone.now()
            events = obj.hoster.filter(
                start_datetime__gte=now, status="active"
            ).order_by("start_datetime")[:10]
        return EventListSerializer(events[:10], many=True).data


    # Replace get_past_events:
    def get_past_events(self, obj):
        events = getattr(obj, "past_events_list", None)
        if events is None:
            now = timezone.now()
            events = obj.hoster.filter(
                start_datetime__lt=now
            ).order_by("-start_datetime")[:10]
        return EventListSerializer(events[:10], many=True).data

    def get_is_following(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            attendee = getattr(request.user, "attendee", None)
            if attendee:
                return Follow.objects.filter(
                    attendee=attendee,
                    host=obj
                ).exists()
        return False


class MessageSerializer(serializers.ModelSerializer):

    class Meta:
        model = Message
        fields = "__all__"
        


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model  = Category
        fields = ["id", "name"]



def event_list_queryset(base_qs=None):
    """
    Use this queryset wherever EventListSerializer is used.
    Resolves all N+1s: media, tickets, attendees_count.
    """
    if base_qs is None:
        base_qs = Event.objects.all()

    # Prefetch only featured media first, fall back handled in serializer
    media_qs = EventMedia.objects.filter(is_featured=True)

    # Prefetch tickets for price + event_status
    tickets_qs = Ticket.objects.all()

    # Annotate attendees_count directly on the queryset
    attendees = (
        Order.objects
        .filter(event=OuterRef("pk"), status="completed")
        .values("event")
        .annotate(c=Count("user", distinct=True))
        .values("c")
    )

    return (
        base_qs
        .select_related("category", "event_location", "host")
        .prefetch_related(
            Prefetch("media", queryset=media_qs, to_attr="featured_media_list"),
            Prefetch("tickets", queryset=tickets_qs, to_attr="all_tickets"),
        )
        .annotate(attendees_count_annotated=Subquery(attendees))
        .order_by("-created_at")
    )


def host_detail_queryset(base_qs=None):
    """
    Use this queryset wherever HostPublicDetailSerializer is used.
    Resolves N+1 on upcoming_events and past_events.
    """
    if base_qs is None:
        base_qs = Host.objects.all()

    now = timezone.now()

    upcoming_qs = event_list_queryset(
        Event.objects.filter(start_datetime__gte=now, status="active")
        .order_by("start_datetime")
    )

    past_qs = event_list_queryset(
        Event.objects.filter(start_datetime__lt=now)
        .order_by("-start_datetime")
    )

    return (
        base_qs
        .annotate(followers_count=Count("followers", distinct=True))
        .prefetch_related(
            Prefetch(
                "hoster",
                queryset=upcoming_qs,
                to_attr="upcoming_events_list",
            ),
            Prefetch(
                "hoster",
                queryset=past_qs,
                to_attr="past_events_list",
            ),
        )
    )


class LocationPageSerializer(serializers.Serializer):
    city              = serializers.CharField()
    description       = serializers.CharField()
    total_events      = serializers.IntegerField()
    total_subscribers = serializers.IntegerField()
    events            = serializers.SerializerMethodField()

    def get_events(self, obj):
        # already evaluated and prefetched — no extra queries
        return EventListSerializer(obj["events"], many=True, context=self.context).data
    


class LocationSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationSubscription
        fields = ["city", "email", "subscribed_at"]


class CategorySubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CategorySubscription
        fields = ["category", "email", "subscribed_at"]



class CategoryPageSerializer(serializers.Serializer):
    name              = serializers.CharField()
    description       = serializers.CharField()
    total_events      = serializers.IntegerField()
    total_subscribers = serializers.IntegerField()
    events            = serializers.SerializerMethodField()

    def get_events(self, obj):
        # obj["events"] is already prefetched — no extra queries
        return EventListSerializer(
            obj["events"],
            many=True,
            context=self.context
        ).data