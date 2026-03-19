from rest_framework import serializers
from transactions.models import IssuedTicket,Withdrawal
from .models import AffliateEarnings,AffiliateLink,Attendee,TwoFactorAuths,GroupMember,TicketGroup,AccountDeletionRequest
from payments.models import PayoutInformation
from events.models import Event
from public.serializers import EventLocationSerializer
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.password_validation import validate_password
from notification.models import NotificationSettings
from host.helpers import generate_checkin_token

class TicketDashboardSerializer(serializers.ModelSerializer):
    sn = serializers.SerializerMethodField()
    qrcode_token = serializers.SerializerMethodField()
    event_name = serializers.CharField(source="event.title", read_only=True)
    category = serializers.CharField(source="event.category.name", read_only=True)
    host=serializers.CharField(source="event.host.id", read_only=True)

    payment = serializers.CharField(source="order.get_status_display", read_only=True)
    event_status = serializers.CharField(source="event.status", read_only=True)

    event_datetime = serializers.DateTimeField(
        source="event.start_datetime",
        read_only=True
    )
    original_price = serializers.DecimalField(
            source="order_ticket.price",
            max_digits=10,
            decimal_places=2,
            read_only=True
        )

    event_image = serializers.SerializerMethodField()
    event_location = serializers.SerializerMethodField()

    ticket_type = serializers.CharField(source="order_ticket.ticket.ticket_type", read_only=True)
    ticket_id = serializers.CharField(read_only=True)
    ticket_status = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = IssuedTicket
        fields = [
            "sn",
            "id",
            "ticket_id",
            "qrcode_token",
            "event_name",
            "event_image",
            "category",
            "payment",
            "event_status",
            "ticket_status",
            "ticket_type",
            "event_datetime",
            "original_price",
            "host",
            "event_location",
        ]

    def get_sn(self, obj):
        view = self.context.get("view")

        if view and hasattr(view, "paginator"):
            page = view.paginator.page
            index = list(page.object_list).index(obj)
            return (page.number - 1) * view.paginator.page_size + index + 1

        return 1

    def get_event_image(self, obj):
        # Use prefetched to_attr list — no extra query
        media_list = getattr(obj.event, "featured_media_list", None)
        if media_list:
            return media_list[0].image_url
        # Fallback
        first = obj.event.media.first()
        return first.image_url if first else None

    def get_event_location(self, obj):
        location = getattr(obj.event, "event_location", None)
        if location is None:
            return None
        return EventLocationSerializer(location).data  # already select_related, no query

    def get_qrcode_token(self, obj):
        return generate_checkin_token(str(obj.id), obj.owner_id)


class FavoriteEventSerializer(serializers.ModelSerializer):
    event_location = EventLocationSerializer(read_only=True)
    event_image = serializers.SerializerMethodField()
    host = serializers.SerializerMethodField()
    event_status = serializers.SerializerMethodField()
    attendees_count = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    event_name=serializers.CharField(source="title", read_only=True)
    event_datetime=serializers.DateTimeField(source="start_datetime", read_only=True)
    event_description=serializers.CharField(source="short_description", read_only=True)
    price=serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = [
            "id", "event_name", "category", "event_datetime", "end_datetime",
            "event_location", "event_image", "host", "event_status", "attendees_count","event_description","price"
        ]
    
    def get_category(self, obj):
        return obj.category.name if obj.category else None


    def get_host(self, obj):
        return getattr(obj.host, "business_name", None)

    def get_event_image(self, obj):
        # Iterate prefetched media — no extra query
        all_media = obj.media.all()
        featured = next((m for m in all_media if m.is_featured), None)
        if featured:
            return featured.image_url
        first = next(iter(all_media), None)
        return first.image_url if first else None

    def get_event_status(self, obj):
        # obj.tickets.all() uses prefetch cache — but only call it once
        tickets = list(obj.tickets.all())
        total_quantity = sum(t.quantity for t in tickets)
        sold_quantity  = sum(getattr(t, "sold_count", 0) for t in tickets)

        if sold_quantity >= total_quantity:
            return "sold-out"
        elif total_quantity > 0 and sold_quantity / total_quantity >= 0.75:
            return "fast-selling"
        elif obj.created_at >= timezone.now() - timedelta(days=7):
            return "new"
        return "normal"

    def get_price(self, obj):
        # Use prefetched tickets
        tickets = list(obj.tickets.all())
        prices = [t.price for t in tickets]
        return min(prices) if prices else None

    def get_attendees_count(self, obj):
        return obj.order_set.filter(status="completed").values("user").distinct().count()




class TicketTransferSerializer(serializers.Serializer):
    ticket_id = serializers.UUIDField()
    recipient_email = serializers.EmailField()



class AffiliateEarningHistorySerializer(serializers.ModelSerializer):
    event_name = serializers.CharField(source="link.event.title", read_only=True)
    tickets_sold = serializers.SerializerMethodField()
    total_sale = serializers.SerializerMethodField()
    your_commission = serializers.DecimalField(source="earning", max_digits=12, decimal_places=2)
    category = serializers.CharField(source="link.event.category.name", read_only=True)
    event_image = serializers.SerializerMethodField()
    

    class Meta:
        model = AffliateEarnings
        fields = ["id", "created_at", "event_name","event_image" ,"category","tickets_sold", "total_sale", "your_commission", "status"]

    def get_tickets_sold(self, obj):
        # Number of tickets sold for this earning (assumes you stored quantity somewhere)
        return getattr(obj, "tickets_sold", 0)

    def get_total_sale(self, obj):
        return getattr(obj, "total_sale", 0)
    
    def get_event_image(self, obj):
        all_media = obj.link.event.media.all()
        featured = next((m for m in all_media if m.is_featured), None)
        if featured:
            return featured.image_url
        first = next(iter(all_media), None)
        return first.image_url if first else None

    


class AffiliateLinkSerializer(serializers.ModelSerializer):
    link = serializers.SerializerMethodField()

    class Meta:
        model = AffiliateLink
        fields = ["id", "event", "code", "link", "clicks", "sales"]

    def get_link(self, obj):
        request = self.context.get("request")

        if not request:
            return None

        domain = request.build_absolute_uri("/")[:-1]

        return f"{domain}/events/{obj.event.id}?ref={obj.code}"



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

class WithdrawalRequestSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    payout_account_id = serializers.UUIDField()


class PayoutInformationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutInformation
        fields = [
            "id",
            "bank_name",
            "account_name",
            "account_number",
            "is_default",
        ]



class AttendeeProfileSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    id = serializers.IntegerField(source="user.id", read_only=True)
    class Meta:
        model = Attendee
        fields = [
            "id",
            "full_name",
            "email",
            "email_verified",
            "phone_number",
            "dob",
            "gender",
            "country",
            "state",
            "city",
            "profile_picture",
            "role"
        ]
        read_only_fields = ["email", "email_verified","id","role"]

    

class TwoFactorToggleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TwoFactorAuths
        fields = ["google", "facebook"]



class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value
    

class NotificationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationSettings
        exclude = ["user", "created_at", "updated_at"]


class GroupMemberSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = GroupMember
        fields = ["email"]


class TicketGroupSerializer(serializers.ModelSerializer):
    members = GroupMemberSerializer(source="group_members", many=True, read_only=True)
    member_count = serializers.SerializerMethodField()
  

    class Meta:
        model = TicketGroup
        fields = ["id", "name", "member_count","members"]

    def get_member_count(self, obj):
        return obj.group_members.count()


class AccountDeletionRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountDeletionRequest
        fields = ["id", "user", "status", "requested_at", "reviewed_at", "admin_notes"]
        read_only_fields = ["id", "status", "requested_at", "reviewed_at", "admin_notes", "user"]


class PayoutInformationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayoutInformation
        fields = ["id", "bank_name", "account_name", "account_number", "is_default", "created_at"]
        read_only_fields = ["id", "created_at"]



class TicketReceiptSerializer(serializers.Serializer):

    # ── Event info ─────────────────────────────────────────────────────────────
    event = serializers.SerializerMethodField()

    # ── Ticket info ────────────────────────────────────────────────────────────
    issued_ticket_id = serializers.IntegerField(source="id")
    ticket_type      = serializers.CharField(source="order_ticket.ticket.ticket_type")
    quantity         = serializers.IntegerField(source="order_ticket.quantity")
    status           = serializers.CharField()

    # ── Current owner ──────────────────────────────────────────────────────────
    current_owner = serializers.SerializerMethodField()

    # ── Billing info (who paid) ────────────────────────────────────────────────
    billed_to = serializers.SerializerMethodField()

    # ── Payment breakdown ──────────────────────────────────────────────────────
    payment = serializers.SerializerMethodField()

    def get_event(self, obj):
        event = obj.event
        media = (
            event.media.filter(is_featured=True).first()
            or event.media.first()
        )
        location = getattr(event, "event_location", None)
        return {
            "id":           str(event.id),
            "event_name":         event.title,
            "category":     event.category.name if event.category else None,
            "event_image": media.image_url if media else None,
            "event_location":     {
                "venue":   location.venue_name  if location else None,
                "address": location.address     if location else None,
                "city":    location.city        if location else None,
                "state":   location.state       if location else None,
                "country": location.country     if location else None,
            } if location else None,
            "event_datetime": event.start_datetime,
            "end_datetime":   event.end_datetime,
        }

    def get_current_owner(self, obj):
        attendee = getattr(obj.owner, "attendee_profile", None)
        return {
            "full_name": attendee.full_name if attendee else obj.owner.email,
            "email":     obj.owner.email,
            "phone":     attendee.phone_number if attendee else None,
        }

    def get_billed_to(self, obj):
        order = obj.order
        # The person who placed the order (may differ from current owner if transferred)
        original_user = order.user
        attendee = getattr(original_user, "attendee_profile", None) if original_user else None
        return {
            "full_name":    attendee.full_name if attendee else (order.full_name or order.email),
            "email":        original_user.email if original_user else order.email,
            "phone_number": order.phone_number,
        }

    def get_payment(self, obj):
        order = obj.order

        # Resolve payment record linked to this order
        from django.contrib.contenttypes.models import ContentType
        from payments.models import Payment

        try:
            ct      = ContentType.objects.get_for_model(order)
            payment = Payment.objects.get(content_type=ct, object_id=order.id)
        except Payment.DoesNotExist:
            payment = None

        # Amount breakdown
        subtotal       = obj.order_ticket.quantity * obj.order_ticket.price
        discount       = order.discount or 0
        fees           = order.fees    or 0

        # Derive service charge and tax from fees
        # Standard split: 70% service charge, 30% tax — adjust to your fee structure
        service_charge = round(float(fees) * 0.70, 2)
        tax            = round(float(fees) * 0.30, 2)

        return {
            "payment_date":    payment.created_at   if payment else order.created_at,
            "payment_method":  payment.provider      if payment else order.payment_method,
            "provider":        payment.provider      if payment else None,
            "subtotal":        str(subtotal),
            "discount":        str(discount),
            "service_charge":  str(service_charge),
            "tax":             str(tax),
            "total_amount":    str(order.total_amount),
            "status":          payment.status if payment else order.status,
        }




class PrivacySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendee
        fields = ["show_events_attending", "show_favorites"]