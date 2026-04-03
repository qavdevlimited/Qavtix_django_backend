from rest_framework import serializers, status

from host.models import HostActivity



class AdminLoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class AdminOTPVerifySerializer(serializers.Serializer):
    temp_token = serializers.UUIDField()
    otp        = serializers.CharField(min_length=6, max_length=6)




class RevenueAnalyticsResponseSerializer(serializers.Serializer):
    total_revenue = serializers.FloatField()
    daily_breakdown = serializers.ListField(child=serializers.DictField())


class TicketAnalyticsResponseSerializer(serializers.Serializer):
    total_tickets = serializers.IntegerField()
    ticket_breakdown = serializers.DictField()
    ticket_percentages = serializers.DictField()
    most_purchased_ticket = serializers.CharField(allow_null=True)
    quantity_buckets = serializers.DictField()


class HostActivitySerializer(serializers.ModelSerializer):

    class Meta:
        model = HostActivity
        fields = [
            "id",
            "activity_type",
            "message",
            "metadata",
            "created_at"
        ]


class AdminCustomerCardSerializer(serializers.Serializer):
    total_customers = serializers.IntegerField()
    new_this_period = serializers.IntegerField()
    repeat_buyers   = serializers.IntegerField()
    average_spend   = serializers.DecimalField(max_digits=12, decimal_places=2)
 
 
class AdminCustomerListSerializer(serializers.Serializer):
    """One row per attendee in the admin customer list."""
 
    # Profile info
    user_id         = serializers.IntegerField(source="user.id")
    full_name       = serializers.CharField(allow_null=True)
    email           = serializers.CharField(source="user.email")
    profile_picture = serializers.URLField(allow_null=True)
    date_joined     = serializers.DateTimeField(source="registration_date")
 
    # Address
    country = serializers.CharField(allow_null=True)
    state   = serializers.CharField(allow_null=True)
    city    = serializers.CharField(allow_null=True)
 
    # Contact
    phone_number = serializers.CharField(allow_null=True)
 
    # Stats — annotated in service
    tickets_bought = serializers.SerializerMethodField()
    total_spend    = serializers.SerializerMethodField()
 
    # Status
    status = serializers.SerializerMethodField()
 
    def get_tickets_bought(self, obj):
        return getattr(obj, "tickets_bought", None) or 0
 
    def get_total_spend(self, obj):
        val = getattr(obj, "total_spend", None)
        return str(val) if val else "0.00"
 
    def get_status(self, obj):
        from administrator.service.customer_service import AdminCustomerListService
        return AdminCustomerListService.get_customer_status(obj)
 
 

 
class AdminAffiliateCardSerializer(serializers.Serializer):
    total_affiliates  = serializers.IntegerField()
    affiliate_growth  = serializers.FloatField(help_text="% change vs previous period")
    total_clicks      = serializers.IntegerField()
    clicks_growth     = serializers.FloatField()
    conversion_rate   = serializers.FloatField(help_text="sales/clicks * 100")
    conversion_rate_growth = serializers.FloatField()
    total_commission  = serializers.DecimalField(max_digits=14, decimal_places=2)
    commission_growth = serializers.FloatField()
 
 
class AdminAffiliateListSerializer(serializers.Serializer):
    """One row per affiliate link in the admin affiliate list."""
 
    # Affiliate identity
    referral_id     = serializers.UUIDField(source="code")
    affiliate_name  = serializers.SerializerMethodField()
    affiliate_email = serializers.CharField(source="user.email")
    profile_picture = serializers.SerializerMethodField()
 
    # Event
    event_id   = serializers.UUIDField(source="event.id")
    event_name = serializers.CharField(source="event.title")
 
    # Performance
    clicks           = serializers.IntegerField()
    signups          = serializers.IntegerField(source="sales")  # sales = conversions
    conversion       = serializers.SerializerMethodField()
    commission_earned = serializers.SerializerMethodField()
    last_activity    = serializers.SerializerMethodField()
 
    def get_affiliate_name(self, obj):
        attendee = getattr(obj.user, "attendee_profile", None)
        return attendee.full_name if attendee else obj.user.email
 
    def get_profile_picture(self, obj):
        attendee = getattr(obj.user, "attendee_profile", None)
        return attendee.profile_picture if attendee else None
 
    def get_conversion(self, obj):
        if not obj.clicks:
            return 0.0
        return round((obj.sales / obj.clicks) * 100, 2)
 
    def get_commission_earned(self, obj):
        val = getattr(obj, "total_commission", None)
        return str(val) if val else "0.00"
 
    def get_last_activity(self, obj):
        return getattr(obj, "updated_at", None)
 
 

 
class AdminWithdrawalListSerializer(serializers.Serializer):
    """One row per withdrawal in the admin withdrawal history."""
 
    payment_id = serializers.UUIDField(source="id")
 
    # Profile info
    profile = serializers.SerializerMethodField()
 
    # Bank account
    bank_account = serializers.SerializerMethodField()
 
    # Details
    withdrawal_date = serializers.DateTimeField(source="created_at")
    amount          = serializers.DecimalField(max_digits=12, decimal_places=2)
    status          = serializers.CharField()
 
    def get_profile(self, obj):
        attendee = getattr(obj.user, "attendee_profile", None)
        return {
            "full_name":       attendee.full_name       if attendee else obj.user.email,
            "email":           obj.user.email,
            "profile_picture": attendee.profile_picture if attendee else None,
        }
 
    def get_bank_account(self, obj):
        acct = obj.payout_account
        return {
            "account_number": acct.account_number,
            "account_name":   acct.account_name,
            "bank_name":      acct.bank_name,
        }
 
 