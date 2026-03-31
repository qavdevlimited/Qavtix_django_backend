import django
from django.utils import timezone
from decimal import Decimal
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from payments.models import PayoutInformation
from  events.models import Event, Ticket, PromoCode, EventMedia, EventLocation, OrganizerSocialLink, Tag,EventPermission
from public.models import Follow
from transactions.models import Withdrawal
from django.db.models import Sum
from datetime import timedelta
from django.db.models import Count

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
            'id','ticket_type', 'description', 'price', 'quantity', 'per_person_max',
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
    event_location = EventLocationNestedSerializer(required=True)
    social_links = OrganizerSocialLinkNestedSerializer(many=True, required=False)
    permissions=EventPermissionSerializer(many=True,required=False)
    tags = serializers.SlugRelatedField(slug_field='name', queryset=Tag.objects.all(), many=True)
    media = EventMediaNestedSerializer(many=True, required=False)
    event_name=serializers.CharField(source="title")
    event_status=serializers.CharField(source="status", read_only=True)

    class Meta:
        model = Event
        fields = [
            'id', 'event_name', 'category', 'tags', 'event_type', 'start_datetime', 'end_datetime',
            'location_type', 'short_description', 'full_description',
            'organizer_display_name', 'organizer_description', 'public_email', 'phone_number',
            'refund_policy', 'refund_percentage', 'qr_enabled', 'age_restriction',
            'order_confirmation', 'ticket_delivery', 'reminders', 'post_event_emails',
            'customize_sender_name', 'affiliate_enabled', 'commission_percentage',
            'affiliate_start', 'affiliate_end',
            'event_location', 'social_links', 'tickets','permissions','event_status','media',"currency"
        ]
    
    def validate(self, attrs):
        instance = getattr(self, "instance", None)  # only exists on update
        if instance and str(instance.status).lower() == "banned":
            from .exceptions import EventBannedException
            raise EventBannedException()  
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if not request or not hasattr(request.user, "host_profile"):
            raise serializers.ValidationError("Only hosts can create events.")

        host = request.user.host_profile  # automatically assign host

        tickets_data = validated_data.pop('tickets')
        location_data = validated_data.pop('event_location')
        permission_data=validated_data.pop('permissions', [])
        social_links_data = validated_data.pop('social_links', [])
        tags_data = validated_data.pop('tags', [])
        media_data = validated_data.pop('media', [])

        from payments.services.currency_utils import get_currency_for_host
        validated_data["currency"] = get_currency_for_host(host)

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
    event_location = serializers.SerializerMethodField()
    tickets_sold_percentage = serializers.SerializerMethodField()
    tickets_total_revenue = serializers.SerializerMethodField()
    category= serializers.CharField(source="category.name", read_only=True)
    event_image=serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            "id",
            "status",
            "title",
            "category",
            "event_image",
            "start_datetime",
            "event_location",
            "tickets_sold_percentage",
            "tickets_total_revenue",
            
            "views_count",
            "saves_count",
        ]

    def get_event_image(self, obj):
        # Get only the featured media
        featured_media = obj.media.filter(is_featured=True).first()
        if featured_media:
            return {
                "image_url": featured_media.image_url,
                "video_url": featured_media.video_url
            }
        return None

    def get_event_location(self, obj):
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
    event_location = EventLocationNestedSerializer(required=True)
    social_links = OrganizerSocialLinkNestedSerializer(many=True, required=False)
    tags = serializers.SlugRelatedField(slug_field='name', queryset=Tag.objects.all(), many=True)
    event_image = EventMediaNestedSerializer(many=True, required=False)
    attendees_count = serializers.SerializerMethodField()
    event_status=serializers.SerializerMethodField()
    is_favorite = serializers.SerializerMethodField()
    category= serializers.CharField(source="category.name", read_only=True)
    is_following = serializers.SerializerMethodField()
    is_trending=serializers.SerializerMethodField()
    is_filling_fast=serializers.SerializerMethodField()
    organizer_id=serializers.IntegerField(source='host.id')
    user_ticket_summary = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = [
            'id', 'title', 'category', 'tags', 'event_type', 'start_datetime', 'end_datetime',
            'location_type', 'short_description', 'full_description',
            'organizer_display_name', 'organizer_description', 'public_email', 'phone_number',
            'event_location', 'social_links', 'tickets','event_status','event_image','attendees_count',
            'age_restriction','is_favorite','is_following','is_trending','is_filling_fast','organizer_id','user_ticket_summary','currency'
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

    def get_user_ticket_summary(self, obj):
        """
        Returns the user's ticket(s) for this event with:
        - issued_ticket_id
        - ticket_type  
        - status
        """
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None

        user = request.user

        from transactions.models import IssuedTicket

        # Fetch actual ticket details (not just counts)
        issued_tickets = IssuedTicket.objects.filter(
            event=obj,
            owner=user
        ).select_related('order_ticket__ticket')   # Important for performance

        if not issued_tickets.exists():
            return None

        ticket_list = []
        for it in issued_tickets:
            ticket_list.append({
                "issued_ticket_id": int(it.id),
                "ticket_type": it.order_ticket.ticket.ticket_type,
                "status": it.status,
                "status_display": it.get_status_display(),   # e.g. "Active", "Cancelled"
            })

        # If user has only one ticket, return it directly (most common case)
        if len(ticket_list) == 1:
            return ticket_list[0]

        # If user has multiple tickets, return as list
        return {
            "has_multiple": True,
            "total": len(ticket_list),
            "tickets": ticket_list
        }


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


class WithdrawalHistorySerializer(serializers.ModelSerializer):
    bank_account = serializers.CharField(source="payout_account.account_number")
    bank_name = serializers.CharField(source="payout_account.bank_name")
    account_name=serializers.CharField(source="payout_account.account_name")
    status = serializers.CharField(source="get_status_display")

    class Meta:
        model = Withdrawal
        fields = [
            "id",
            "created_at",
            "amount",
            "bank_name",
            "bank_account",
            "account_name",
            "status",
        ]


class RevenueCardSerializer(serializers.Serializer):
    """
    Cards shown on the host revenue overview page.
    """
    total_revenue   = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_payout    = serializers.DecimalField(max_digits=12, decimal_places=2)
    available_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    next_payout_date  = serializers.DateField()


class WithdrawalHistorySerializer(serializers.Serializer):
    """
    Single withdrawal row in the history list.
    """
    id          = serializers.UUIDField()
    amount      = serializers.DecimalField(max_digits=12, decimal_places=2)
    status      = serializers.CharField()
    created_at  = serializers.DateTimeField()
    updated_at  = serializers.DateTimeField()
    payout_account = serializers.SerializerMethodField()

    def get_payout_account(self, obj):
        acct = obj.payout_account
        return {
            "id":           acct.id,
            "bank_name":    getattr(acct, "bank_name", None),
            "account_name": getattr(acct, "account_name", None),
            "account_number": getattr(acct, "account_number", None),
        }


# ── Withdrawal Request ─────────────────────────────────────────────────────────

class HostWithdrawalRequestSerializer(serializers.Serializer):
    """
    Payload for POST /finance/withdraw/
    """
    amount            = serializers.DecimalField(max_digits=12, decimal_places=2)
    payout_account_id = serializers.UUIDField()

    def validate_amount(self, value):
        if value <= Decimal("0.00"):
            raise serializers.ValidationError(
                "Withdrawal amount must be greater than zero."
            )
        return value



class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value
    



class PromoCodeListSerializer(serializers.Serializer):
    id             = serializers.IntegerField()
    code           = serializers.CharField()
    status         = serializers.SerializerMethodField()
    discount_percentage = serializers.IntegerField()
    usage_limit    = serializers.IntegerField(source="maximum_users")
    usage_count    = serializers.IntegerField()        # annotated in view
    revenue_impact = serializers.DecimalField(max_digits=12, decimal_places=2)  # annotated
    expiry_date    = serializers.DateField(source="valid_till")
    event_name     = serializers.CharField(source="ticket.event.title")
    event_category = serializers.SerializerMethodField()
    event_image    = serializers.SerializerMethodField()

    def get_status(self, obj):
        return "active" if obj.valid_till >= timezone.now().date() else "ended"

    def get_event_category(self, obj):
        cat = obj.ticket.event.category
        return cat.name if cat else None

    def get_event_image(self, obj):
        media = obj.ticket.event.media.filter(is_featured=True).first() \
                or obj.ticket.event.media.first()
        return media.image_url if media else None


class PromoCodeCreateSerializer(serializers.Serializer):
    event_id            = serializers.UUIDField()
    code                = serializers.CharField(max_length=50)
    discount_percentage = serializers.IntegerField(min_value=1, max_value=100)
    usage_limit         = serializers.IntegerField(min_value=1)
    valid_until         = serializers.DateField()

    def validate_valid_until(self, value):
        if value < timezone.now().date():
            raise serializers.ValidationError("Expiry date must be in the future.")
        return value


# ── Affiliate ──────────────────────────────────────────────────────────────────

class AffiliateListSerializer(serializers.Serializer):
    """One row per affiliate link on the host affiliate dashboard."""
    id              = serializers.IntegerField()
    affiliate_url   = serializers.SerializerMethodField()

    # Identity — sourced from Attendee.full_name via user.attendee_profile
    affiliate_name  = serializers.SerializerMethodField()
    affiliate_email = serializers.CharField(source="user.email")

    # Event info
    event_name      = serializers.CharField(source="event.title")
    category  = serializers.SerializerMethodField()
    event_image     = serializers.SerializerMethodField()

    # Performance
    clicks          = serializers.IntegerField()
    sales           = serializers.IntegerField()
    conversion_rate = serializers.SerializerMethodField()   # sales / clicks %
    rank            = serializers.IntegerField()            # attached in service
    total_earnings  = serializers.DecimalField(max_digits=12, decimal_places=2)

    created_at      = serializers.DateTimeField()

    def get_affiliate_url(self, obj):
        return obj.get_url()

    def get_affiliate_name(self, obj):
        """Read full_name from the Attendee profile, fall back to email."""
        attendee = getattr(obj.user, "attendee_profile", None)
        return attendee.full_name if attendee else obj.user.email

    def get_category(self, obj):
        cat = obj.event.category
        return cat.name if cat else None

    def get_event_image(self, obj):
        media = (
            obj.event.media.filter(is_featured=True).first()
            or obj.event.media.first()
        )
        return media.image_url if media else None

    def get_conversion_rate(self, obj):
        """
        Conversion rate = (sales / clicks) × 100, rounded to 2 dp.
        Returns 0.0 when there are no clicks yet.
        """
        if not obj.clicks:
            return 0.0
        return round((obj.sales / obj.clicks) * 100, 2)


class AffiliateCardSerializer(serializers.Serializer):
    total_affiliates       = serializers.IntegerField()
    new_this_month         = serializers.IntegerField()
    total_tickets_sold     = serializers.IntegerField()
    total_commission_paid  = serializers.DecimalField(max_digits=12, decimal_places=2)




class EmailCampaignListSerializer(serializers.Serializer):
    id              = serializers.UUIDField()
    campaign_name   = serializers.CharField()
    subject         = serializers.CharField()
    sender_name     = serializers.CharField()
    sender_email    = serializers.EmailField()
    recipients      = serializers.IntegerField(source="recipients_count")
    sent_at         = serializers.DateTimeField()
    open_rate       = serializers.FloatField()
    click_rate      = serializers.FloatField()
    status          = serializers.CharField()

    # Event info
    event_id        = serializers.UUIDField(source="event.id")
    event_name      = serializers.CharField(source="event.title")
    event_category  = serializers.SerializerMethodField()
    event_image     = serializers.SerializerMethodField()

    def get_event_category(self, obj):
        cat = obj.event.category
        return cat.name if cat else None

    def get_event_image(self, obj):
        media = (
            obj.event.media.filter(is_featured=True).first()
            or obj.event.media.first()
        )
        return media.image_url if media else None


class EmailCampaignCreateSerializer(serializers.Serializer):
    event_id      = serializers.UUIDField()
    campaign_name = serializers.CharField(max_length=255)
    subject       = serializers.CharField(max_length=255)
    html_content  = serializers.CharField()
    sender_name   = serializers.CharField(max_length=255, required=False)
    sender_email  = serializers.EmailField(required=False)

class SingleEmailCampaignSerializer(serializers.Serializer):
    recipient_email = serializers.EmailField()
    subject      = serializers.CharField(max_length=255)
    html_content = serializers.CharField()
    sender_name  = serializers.CharField(max_length=255, required=False)
    sender_email = serializers.EmailField(required=False)


class EmailCampaignSendSerializer(serializers.Serializer):
    """Body is empty — campaign_id comes from the URL."""
    pass


#FOR CHECKIN

# ── Overview (cards) ───────────────────────────────────────────────────────────

class CheckInCardSerializer(serializers.Serializer):
    total_tickets   = serializers.IntegerField()
    total_checkins  = serializers.IntegerField()
    issues          = serializers.IntegerField(
        help_text="Duplicate or invalid scans"
    )


# ── Attendee list ──────────────────────────────────────────────────────────────

class CheckInAttendeeSerializer(serializers.Serializer):
    """One row per issued ticket — shown in the attendee check-in list."""

    # Attendee identity
    full_name    = serializers.SerializerMethodField()
    email        = serializers.SerializerMethodField()

    # Ticket info
    issued_ticket_id = serializers.UUIDField(source="id")
    ticket_type      = serializers.CharField(
        source="order_ticket.ticket.ticket_type"
    )
    qr_token         = serializers.SerializerMethodField()

    # Event info
    event_name     = serializers.CharField(source="event.title")
    event_category = serializers.SerializerMethodField()
    event_image    = serializers.SerializerMethodField()

    # Check-in info
    checkin_status  = serializers.SerializerMethodField()
    # possible values: pending | checked_in | invalid | already_checked_in
    checked_in_at   = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        attendee = getattr(obj.owner, "attendee_profile", None)
        return attendee.full_name if attendee else obj.owner.email

    def get_email(self, obj):
        return obj.owner.email

    def get_qr_token(self, obj):
        from .helpers import generate_checkin_token
        # Bind token to current owner — transfers invalidate old tokens
        return generate_checkin_token(str(obj.id), obj.owner_id)

    def get_event_category(self, obj):
        cat = obj.event.category
        return cat.name if cat else None

    def get_event_image(self, obj):
        media = (
            obj.event.media.filter(is_featured=True).first()
            or obj.event.media.first()
        )
        return media.image_url if media else None

    def get_checkin_status(self, obj):
        checkin = getattr(obj, "checkin", None)
        if checkin is None:
            return "pending"
        return checkin.status

    def get_checked_in_at(self, obj):
        checkin = getattr(obj, "checkin", None)
        return checkin.checked_in_at if checkin else None


# ── Scan result ────────────────────────────────────────────────────────────────

class ScanResultSerializer(serializers.Serializer):
    """Response returned after a QR scan."""
    status           = serializers.CharField()
    message          = serializers.CharField()
    issued_ticket_id = serializers.UUIDField(allow_null=True)
    full_name        = serializers.CharField(allow_null=True)
    ticket_type      = serializers.CharField(allow_null=True)
    event_name       = serializers.CharField(allow_null=True)
    checked_in_at    = serializers.DateTimeField(allow_null=True)


class ScanInputSerializer(serializers.Serializer):
    token = serializers.CharField()



# ── Dashboard cards + chart ────────────────────────────────────────────────────

class DashboardCardSerializer(serializers.Serializer):
    total_revenue     = serializers.DecimalField(max_digits=14, decimal_places=2)
    tickets_sold      = serializers.IntegerField()
    active_events     = serializers.IntegerField()
    pending_payouts   = serializers.DecimalField(max_digits=14, decimal_places=2)

    # % or count changes shown under each card
    revenue_change        = serializers.FloatField(help_text="% change vs last month")
    tickets_sold_change   = serializers.IntegerField(help_text="Count change this week")
    active_events_change  = serializers.IntegerField(help_text="New active events this week")
    pending_payouts_change= serializers.IntegerField(help_text="New pending payouts this week")


class RevenueChartPointSerializer(serializers.Serializer):
    label  = serializers.CharField(help_text="Month name e.g. Jan, Feb")
    month  = serializers.IntegerField(help_text="Month number 1-12")
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)


# ── Activity + Notifications ───────────────────────────────────────────────────

class HostActivitySerializer(serializers.Serializer):
    id            = serializers.UUIDField()
    activity_type = serializers.CharField()
    message       = serializers.CharField()
    metadata      = serializers.DictField()
    created_at    = serializers.DateTimeField()


class HostNotificationSerializer(serializers.Serializer):
    id                = serializers.UUIDField()
    notification_type = serializers.CharField()
    title             = serializers.CharField()
    message           = serializers.CharField()
    is_read           = serializers.BooleanField()
    created_at        = serializers.DateTimeField()


# ── Trending tickets ───────────────────────────────────────────────────────────

class TrendingTicketSerializer(serializers.Serializer):
    ticket_id       = serializers.IntegerField(source="id")
    ticket_type     = serializers.CharField()
    event_name      = serializers.CharField(source="event.title")
    event_category  = serializers.SerializerMethodField()
    event_image     = serializers.SerializerMethodField()
    tickets_sold    = serializers.IntegerField(source="sold_count")
    conversion_rate = serializers.SerializerMethodField()
    revenue         = serializers.DecimalField(max_digits=14, decimal_places=2)

    def get_event_category(self, obj):
        cat = obj.event.category
        return cat.name if cat else None

    def get_event_image(self, obj):
        media = (
            obj.event.media.filter(is_featured=True).first()
            or obj.event.media.first()
        )
        return media.image_url if media else None

    def get_conversion_rate(self, obj):
        """
        conversion_rate = (tickets_sold / total_capacity) * 100
        """
        if not obj.quantity:
            return 0.0
        return round((obj.sold_count / obj.quantity) * 100, 2)




#SALES ANALYSIS
class SalesCardSerializer(serializers.Serializer):
    # Row 1
    total_revenue        = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_revenue_change = serializers.DecimalField(
        max_digits=14, decimal_places=2,
        help_text="Raw change vs previous period e.g. +733000"
    )
    tickets_sold         = serializers.IntegerField()
    conversion_rate      = serializers.FloatField(help_text="sold / capacity * 100")
    conversion_change    = serializers.FloatField(help_text="% change vs previous period")
    average_order_value  = serializers.DecimalField(max_digits=14, decimal_places=2)
    aov_change           = serializers.FloatField(help_text="% change vs previous period")

    # Row 2
    page_views    = serializers.IntegerField()
    refunds       = serializers.IntegerField()
    repeat_buyers = serializers.IntegerField()


# ── Endpoint 2: Graphs ─────────────────────────────────────────────────────────

class RevenuePointSerializer(serializers.Serializer):
    label  = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class TicketTypeSalesSerializer(serializers.Serializer):
    ticket_type = serializers.CharField()
    count       = serializers.IntegerField()
    percentage  = serializers.FloatField()


class SalesPeriodBreakdownSerializer(serializers.Serializer):
    period_label   = serializers.CharField()
    total          = serializers.IntegerField()
    by_ticket_type = TicketTypeSalesSerializer(many=True)


class SalesBreakdownSerializer(serializers.Serializer):
    overall   = TicketTypeSalesSerializer(many=True)
    by_period = SalesPeriodBreakdownSerializer(many=True)


class WeekDayPointSerializer(serializers.Serializer):
    day       = serializers.CharField()
    date      = serializers.DateField()
    morning   = serializers.IntegerField()
    afternoon = serializers.IntegerField()
    evening   = serializers.IntegerField()
    total     = serializers.IntegerField()


class WeekAnalysisSerializer(serializers.Serializer):
    change_vs_last_week = serializers.FloatField()
    label               = serializers.CharField()
    days                = WeekDayPointSerializer(many=True)


class GeoLocationSerializer(serializers.Serializer):
    city    = serializers.CharField()
    state   = serializers.CharField()
    tickets = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    clicks  = serializers.IntegerField()


class BestLocationSerializer(serializers.Serializer):
    label   = serializers.CharField()
    tickets = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    clicks  = serializers.IntegerField()


class GeoBreakdownSerializer(serializers.Serializer):
    locations     = GeoLocationSerializer(many=True)
    best_location = BestLocationSerializer(allow_null=True)


# ── Endpoint 3: Transaction History ───────────────────────────────────────────

class TransactionHistorySerializer(serializers.Serializer):
    payment_id    = serializers.UUIDField(source="id")
    purchased_by  = serializers.SerializerMethodField()
    event         = serializers.SerializerMethodField()
    purchase_date = serializers.DateTimeField(source="created_at")
    quantity      = serializers.SerializerMethodField()
    amount        = serializers.DecimalField(
        max_digits=14, decimal_places=2, source="total_amount"
    )
    status = serializers.CharField()

    def get_purchased_by(self, obj):
        attendee = getattr(obj.user, "attendee_profile", None) if obj.user else None
        return {
            "full_name": attendee.full_name if attendee else (obj.full_name or obj.email),
            "email":     obj.user.email if obj.user else obj.email,
        }

    def get_event(self, obj):
        event = obj.event
        media = (
            event.media.filter(is_featured=True).first()
            or event.media.first()
        )
        return {
            "id":       str(event.id),
            "name":     event.title,
            "image":    media.image_url if media else None,
            "category": event.category.name if event.category else None,
        }

    def get_quantity(self, obj):
        return sum(t.quantity for t in obj.tickets.all())



class DownloadEventAttendeeSerializer(serializers.Serializer):
    order_id      = serializers.UUIDField(source="order.id")
    full_name     = serializers.SerializerMethodField()
    email         = serializers.SerializerMethodField()
    ticket_type   = serializers.CharField(source="order_ticket.ticket.ticket_type")
    quantity      = serializers.IntegerField(source="order_ticket.quantity")
    amount_paid   = serializers.DecimalField(
        max_digits=12, decimal_places=2, source="order.total_amount"
    )
    purchase_date = serializers.DateTimeField(source="order.created_at")
    status        = serializers.CharField()          # IssuedTicket.status
    checkin_status = serializers.SerializerMethodField()
    checked_in_at  = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        attendee = getattr(obj.owner, "attendee_profile", None)
        return attendee.full_name if attendee else (obj.owner.get_full_name() or obj.owner.email)

    def get_email(self, obj):
        return obj.owner.email

    def get_checkin_status(self, obj):
        checkin = getattr(obj, "checkin", None)
        return checkin.status if checkin else "pending"

    def get_checked_in_at(self, obj):
        checkin = getattr(obj, "checkin", None)
        return checkin.checked_in_at if checkin else None