from rest_framework import serializers
from  events.models import Event, Ticket, PromoCode, EventMedia, EventLocation, OrganizerSocialLink, Tag,EventPermission

# Ticket promo codes
class PromoCodeNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = PromoCode
        fields = ['code', 'discount_percentage', 'maximum_users', 'valid_till']

# Ticket media
class EventMediaNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventMedia
        fields = ['image_url', 'video_url', 'is_featured']


#Event Permission
class EventPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model=EventPermission
        fields = ['id','email','role','status', 
        ]

# Ticket serializer
class TicketNestedSerializer(serializers.ModelSerializer):
    promo_codes = PromoCodeNestedSerializer(many=True, required=False)

    class Meta:
        model = Ticket
        fields = [
            'ticket_type', 'description', 'price', 'quantity', 'per_person_max',
            'sales_start', 'sales_end', 'promo_codes',
        ]

# Event location
class EventLocationNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventLocation
        fields = ['venue_name', 'address', 'country', 'state', 'city', 'postal_code']

# Organizer social links
class OrganizerSocialLinkNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizerSocialLink
        fields = ['url']

# Event serializer with all nested fields
class EventSerializer(serializers.ModelSerializer):
    tickets = TicketNestedSerializer(many=True)
    location = EventLocationNestedSerializer(required=True)
    social_links = OrganizerSocialLinkNestedSerializer(many=True, required=False)
    permissions=EventPermissionSerializer(many=True,required=False)
    tags = serializers.SlugRelatedField(slug_field='name', queryset=Tag.objects.all(), many=True)
    media = EventMediaNestedSerializer(many=True, required=False)

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'category', 'tags', 'event_type', 'start_datetime', 'end_datetime',
            'location_type', 'short_description', 'full_description',
            'organizer_display_name', 'organizer_description', 'public_email', 'phone_number',
            'refund_policy', 'refund_percentage', 'qr_enabled', 'age_restriction',
            'order_confirmation', 'ticket_delivery', 'reminders', 'post_event_emails',
            'customize_sender_name', 'affiliate_enabled', 'commission_percentage',
            'affiliate_start', 'affiliate_end',
            'location', 'social_links', 'tickets','permissions','status','media'
        ]
    
    def validate(self, attrs):
        instance = getattr(self, "instance", None)  # only exists on update
        if instance and str(instance.status).lower() == "banned":
            from .exceptions import EventBannedException
            raise EventBannedException()  # <- this triggers your handler
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if not request or not hasattr(request.user, "host_profile"):
            raise serializers.ValidationError("Only hosts can create events.")

        host = request.user.host_profile  # automatically assign host

        tickets_data = validated_data.pop('tickets')
        location_data = validated_data.pop('location')
        permission_data=validated_data.pop('permissions', [])
        social_links_data = validated_data.pop('social_links', [])
        tags_data = validated_data.pop('tags', [])
        media_data = validated_data.pop('media', [])

        from django.db import transaction

        with transaction.atomic():
            event = Event.objects.create(host=host, **validated_data)
            event.tags.set(tags_data)

            # create location
            EventLocation.objects.create(event=event, **location_data)

            #create permissions
            for permission in permission_data:
                EventPermission.objects.create(event=event, **permission)

            # create social links
            for link_data in social_links_data:
                OrganizerSocialLink.objects.create(event=event, **link_data)

            # create event media
            for media_item in media_data:
                EventMedia.objects.create(event=event, **media_item)

            # create tickets + nested promo codes and media
            for ticket_data in tickets_data:
                promo_codes_data = ticket_data.pop('promo_codes', [])
                ticket = Ticket.objects.create(event=event, **ticket_data)

                for promo_data in promo_codes_data:
                    PromoCode.objects.create(ticket=ticket, **promo_data)

    

        return event
    





class EventTableSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    tickets_sold_percentage = serializers.SerializerMethodField()
    tickets_total_revenue = serializers.SerializerMethodField()
    category_name = serializers.CharField(source="category.name", read_only=True)
    media=serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id",
            "status",
            "title",
            "category_name",
            "media",
            "start_datetime",
            "location",
            "tickets_sold_percentage",
            "tickets_total_revenue",
            
            "views_count",
            "saves_count",
        ]

    def get_media(self, obj):
        # Get only the featured media
        featured_media = obj.media.filter(is_featured=True).first()
        if featured_media:
            return {
                "image_url": featured_media.image_url,
                "video_url": featured_media.video_url
            }
        return None

    def get_location(self, obj):
        if obj.location:
            return f"{obj.location.address}, {obj.location.city}, {obj.location.state}, {obj.location.country}"
        return ""

    def get_tickets_sold_percentage(self, obj):
        # tickets = obj.tickets.all()
        # total_qty = sum(t.quantity for t in tickets)
        # sold_qty = sum(t.sold_quantity for t in tickets)
        # if total_qty:
        #     return round((sold_qty / total_qty) * 100)
        return 100

    def get_tickets_total_revenue(self, obj):
        tickets = obj.tickets.all()
        return 100


# Card data serializer (counts per status)
class EventCardSerializer(serializers.Serializer):
    live = serializers.IntegerField()
    draft = serializers.IntegerField()
    ended = serializers.IntegerField()
    cancelled = serializers.IntegerField()




class EventDetailsSerializer(serializers.ModelSerializer):
    tickets = TicketNestedSerializer(many=True)
    location = EventLocationNestedSerializer(required=True)
    social_links = OrganizerSocialLinkNestedSerializer(many=True, required=False)
    tags = serializers.SlugRelatedField(slug_field='name', queryset=Tag.objects.all(), many=True)
    media = EventMediaNestedSerializer(many=True, required=False)
    attendees_count = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'category', 'tags', 'event_type', 'start_datetime', 'end_datetime',
            'location_type', 'short_description', 'full_description',
            'organizer_display_name', 'organizer_description', 'public_email', 'phone_number',
            'location', 'social_links', 'tickets','status','media','attendees_count'
        ]
    
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