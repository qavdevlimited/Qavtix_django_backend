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
        featured_media = obj.event.media.filter(is_featured=True).first()

        if featured_media:
            return featured_media.image_url

        first_media = obj.event.media.first()
        return first_media.image_url if first_media else None

    def get_event_location(self, obj):
        return EventLocationSerializer(obj.event.location).data

    def get_qrcode_token(self, obj):
        return generate_checkin_token(str(obj.id), obj.owner_id)


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
        """
        Return featured image if exists,
        otherwise return first image,
        otherwise None
        """
        event = obj.link.event
        featured = event.media.filter(is_featured=True).first()
        if featured:
            return featured.image_url

        first_image = event.media.first()
        return first_image.image_url if first_image else None


    


class AffiliateLinkSerializer(serializers.ModelSerializer):
    link = serializers.SerializerMethodField()

    class Meta:
        model = AffiliateLink
        fields = ["id", "event", "code", "link", "clicks", "sales"]

    def get_link(self, obj):
        request = self.context.get("request")
        domain = request.build_absolute_uri("/")[:-1]  # remove traili




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
        read_only_fields = ["email", "email_verified","id"]

    

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