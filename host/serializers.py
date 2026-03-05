from rest_framework import serializers
from payments.models import PayoutInformation
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
    


class CustomerCardSerializer(serializers.Serializer):
    """Cards for the customer list page."""
    total_customers = serializers.IntegerField()
    new_this_month = serializers.IntegerField()
    repeat_buyers = serializers.IntegerField()
    average_spend = serializers.DecimalField(max_digits=10, decimal_places=2)


class CustomerListSerializer(serializers.Serializer):
    """Row data for the customer table."""
    user_id = serializers.IntegerField(source="user__id")
    name = serializers.CharField(source="user__attendee_profile__full_name")
    email = serializers.CharField(source="user__email")
    status = serializers.SerializerMethodField()
    events_attended = serializers.IntegerField()
    total_spent = serializers.DecimalField(max_digits=10, decimal_places=2)
    last_purchase_date = serializers.DateTimeField()

    def get_status(self, obj):
        """Classify the customer: top spender, new customer, or repeat buyer."""
        context = self.context
        total_spent = obj.get("total_spent", 0) or 0
        events_attended = obj.get("events_attended", 0) or 0
        top_threshold = context.get("top_threshold", 0)

        if total_spent >= top_threshold and top_threshold > 0:
            return "top_spender"
        if events_attended == 1:
            return "new_customer"
        return "repeat_buyer"


# ── Detail page ────────────────────────────────────────────────────────────────

class AttendeeProfileSerializer(serializers.Serializer):
    """Full attendee profile info shown on the detail page."""
    user_id = serializers.IntegerField()
    full_name = serializers.CharField()
    email = serializers.CharField()
    phone_number = serializers.CharField()
    country = serializers.CharField()
    state = serializers.CharField()
    city = serializers.CharField()
    gender = serializers.CharField()
    dob = serializers.DateField()
    profile_picture = serializers.URLField()
    registration_date = serializers.DateTimeField()
    first_purchase_date = serializers.DateTimeField(allow_null=True)
    last_purchase_date = serializers.DateTimeField(allow_null=True)


class CustomerDetailCardSerializer(serializers.Serializer):
    """4 KPI cards for the customer detail page."""
    total_spent = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_spent_change = serializers.FloatField(help_text="% change vs previous period")

    tickets_bought = serializers.IntegerField()
    tickets_bought_change = serializers.FloatField()

    refund_count = serializers.IntegerField()
    refund_count_change = serializers.FloatField()

    last_order_value = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    last_order_value_change = serializers.FloatField()


class RevenueChartPointSerializer(serializers.Serializer):
    """Single data point on the revenue chart."""
    label = serializers.CharField()        # e.g. "2024-03-01" or "Mon" or "Mar"
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class CustomerOrderHistorySerializer(serializers.Serializer):
    """Order history row on the customer detail page."""
    order_id = serializers.UUIDField()
    event_id = serializers.UUIDField()
    event_name = serializers.CharField()
    event_image = serializers.URLField(allow_null=True, allow_blank=True)
    event_category = serializers.CharField(allow_null=True)
    purchase_date = serializers.DateTimeField()
    quantity = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    status = serializers.CharField()




class PayoutInformationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutInformation
        fields = ["id", "bank_name", "account_name", "account_number", "is_default", "created_at"]
        read_only_fields = ["id", "created_at"]