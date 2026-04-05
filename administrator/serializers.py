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
 
 

class UserDetailCardSerializer(serializers.Serializer):
    total_spent             = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_spent_change      = serializers.FloatField()
    tickets_bought          = serializers.IntegerField()
    tickets_bought_change   = serializers.FloatField()
    refund_count            = serializers.IntegerField()
    refund_count_change     = serializers.FloatField()
    last_order_value        = serializers.DecimalField(max_digits=14, decimal_places=2)
    last_order_value_change = serializers.FloatField()
 
 
class UserDetailChartPointSerializer(serializers.Serializer):
    label  = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
 
 
class UserDetailOrderSerializer(serializers.Serializer):
    """One row per order in the purchase history table."""
    order_id      = serializers.UUIDField(source="id")
    event_id      = serializers.UUIDField(source="event.id")
    event_name    = serializers.CharField(source="event.title")
    event_category = serializers.SerializerMethodField()
    purchase_date = serializers.DateTimeField(source="created_at")
    quantity      = serializers.SerializerMethodField()
    amount        = serializers.DecimalField(max_digits=14, decimal_places=2, source="total_amount")
    status        = serializers.CharField()
    event_image   = serializers.SerializerMethodField()
 
    def get_event_category(self, obj):
        cat = getattr(obj.event, "category", None)
        return cat.name if cat else None
 
    def get_quantity(self, obj):
        # Uses annotated total_qty if available, else sum from prefetch
        annotated = getattr(obj, "total_qty", None)
        if annotated is not None:
            return annotated
        return sum(t.quantity for t in obj.tickets.all())
    

    def get_event_image(self, obj):
        """Return featured image safely"""
        # 1. Use annotated field from queryset (most efficient)
        if hasattr(obj, 'featured_image') and obj.featured_image:
            return obj.featured_image

        # 2. Fallback: Check event media directly (if needed)
        media = getattr(obj.event, 'media', None)
        if media:
            # Prefer featured image
            featured = media.filter(is_featured=True).first()
            if featured and featured.image_url:
                return featured.image_url
            
            # Otherwise take the first image
            first_media = media.first()
            if first_media and first_media.image_url:
                return first_media.image_url

        return None
 
 
class BankAccountSerializer(serializers.Serializer):
    id             = serializers.UUIDField()
    account_name   = serializers.CharField()
    account_number = serializers.CharField()
    bank_name      = serializers.CharField()
    is_default     = serializers.BooleanField()
 
 
class UserDetailProfileSerializer(serializers.Serializer):
    """Full profile card for admin user detail page."""
 
    # Identity
    user_id         = serializers.IntegerField()
    email           = serializers.EmailField()
    full_name       = serializers.CharField()
    phone_number    = serializers.CharField(allow_null=True)
    profile_picture = serializers.URLField(allow_null=True)
    dob             = serializers.DateField(allow_null=True)
    gender          = serializers.CharField(allow_null=True)
    date_joined     = serializers.DateTimeField()
 
    # Location
    country = serializers.CharField(allow_null=True)
    state   = serializers.CharField(allow_null=True)
    city    = serializers.CharField(allow_null=True)
 
    # Host info
    is_host        = serializers.BooleanField()
    business_name  = serializers.CharField(allow_null=True)
    business_type  = serializers.CharField(allow_null=True)
    description    = serializers.CharField(allow_null=True)
    relevant_links = serializers.ListField(child=serializers.CharField(), allow_empty=True)
 
    # Stats
    all_time_spend   = serializers.DecimalField(max_digits=14, decimal_places=2)
    all_time_tickets = serializers.IntegerField()
    first_purchase   = serializers.DateTimeField(allow_null=True)
    last_purchase    = serializers.DateTimeField(allow_null=True)
 
    # Bank accounts
    bank_accounts = BankAccountSerializer(many=True)
 
    # Status
    account_status = serializers.CharField()
    is_active      = serializers.BooleanField()
    wallet_balance = serializers.DecimalField(max_digits=14, decimal_places=2)





# ── Host Cards ────────────────────────────────────────────────────────────────
 
class AdminHostCardSerializer(serializers.Serializer):
    total_hosts       = serializers.IntegerField()
    new_this_period   = serializers.IntegerField()
    new_growth        = serializers.FloatField()
    tickets_sold      = serializers.IntegerField()
    tickets_growth    = serializers.FloatField()
    commission_paid   = serializers.DecimalField(max_digits=14, decimal_places=2)
    commission_growth = serializers.FloatField()
 
 
# ── Host List ─────────────────────────────────────────────────────────────────
 
class AdminHostListSerializer(serializers.Serializer):
    host_id        = serializers.IntegerField(source="id")
 
    # Owner info
    owner_name     = serializers.CharField(source="full_name")
    owner_email    = serializers.CharField(source="user.email")
    profile_picture = serializers.URLField(allow_null=True)
 
    # Business
    business_name  = serializers.CharField()
    business_type  = serializers.CharField(allow_null=True)
 
    # Stats — annotated
    event_count    = serializers.IntegerField()
    followers      = serializers.IntegerField()
    total_revenue  = serializers.SerializerMethodField()
 
    # Status
    status         = serializers.SerializerMethodField()
    verified       = serializers.BooleanField()
    date_joined    = serializers.DateTimeField(source="registration_date")
 
    def get_total_revenue(self, obj):
        val = getattr(obj, "total_revenue", None)
        return str(val) if val else "0.00"
 
    def get_status(self, obj):
        from administrator.service.host_service import AdminHostListService
        return AdminHostListService.get_host_status(obj)
 
 
# ── Pending Verification List ─────────────────────────────────────────────────
 
class AdminHostVerificationListSerializer(serializers.Serializer):
    host_id             = serializers.IntegerField(source="id")
    business_name       = serializers.CharField()
    owner_name          = serializers.CharField(source="full_name")
    owner_email         = serializers.CharField(source="user.email")
    owner_phone         = serializers.CharField(source="phone_number")
    profile_picture     = serializers.URLField(allow_null=True)
    signup_date         = serializers.DateTimeField(source="registration_date")
    account_type        = serializers.CharField(source="business_type", allow_null=True)
    status              = serializers.SerializerMethodField()
 
    # KYC info for review
    registration_number = serializers.CharField(allow_null=True, allow_blank=True)
    tax_id              = serializers.CharField(allow_null=True, allow_blank=True)
    nin                 = serializers.CharField(allow_null=True, allow_blank=True)
 
    def get_status(self, obj):
        if not obj.user.is_active:
            return "suspended"
        return "pending_verification"
 
 
# ── Host Detail Cards ─────────────────────────────────────────────────────────
 
class AdminHostDetailCardSerializer(serializers.Serializer):
    all_time_earnings = serializers.DecimalField(max_digits=14, decimal_places=2)
    current_balance   = serializers.DecimalField(max_digits=14, decimal_places=2)
    all_time_payouts  = serializers.DecimalField(max_digits=14, decimal_places=2)
    next_payout_date  = serializers.DateTimeField(allow_null=True)
 
 
# ── Host Detail Profile ───────────────────────────────────────────────────────
 
class AdminBankAccountSerializer(serializers.Serializer):
    id             = serializers.UUIDField()
    account_name   = serializers.CharField()
    account_number = serializers.CharField()
    bank_name      = serializers.CharField()
    is_default     = serializers.BooleanField()
 
 
class AdminHostDetailProfileSerializer(serializers.Serializer):
    host_id             = serializers.IntegerField()
    full_name           = serializers.CharField()
    email               = serializers.EmailField()
    phone_number        = serializers.CharField(allow_null=True)
    profile_picture     = serializers.URLField(allow_null=True)
    profile_banner      = serializers.URLField(allow_null=True)
    business_name       = serializers.CharField()
    business_type       = serializers.CharField(allow_null=True)
    description         = serializers.CharField(allow_null=True)
    registration_number = serializers.CharField(allow_null=True)
    tax_id              = serializers.CharField(allow_null=True)
    nin                 = serializers.CharField(allow_null=True)
    country             = serializers.CharField()
    state               = serializers.CharField()
    city                = serializers.CharField()
    followers           = serializers.IntegerField()
    verified            = serializers.BooleanField()
    relevant_links      = serializers.ListField(child=serializers.CharField(), allow_empty=True)
    date_joined         = serializers.DateTimeField()
    bank_accounts       = AdminBankAccountSerializer(many=True)
    account_status      = serializers.CharField()
    is_subscribed       = serializers.BooleanField()
    is_verified   = serializers.BooleanField()



    
 
 
# ── Host Detail Events ────────────────────────────────────────────────────────
 
class AdminHostEventSerializer(serializers.Serializer):
    event_id       = serializers.UUIDField(source="id")
    title          = serializers.CharField()
    category       = serializers.SerializerMethodField()
    status         = serializers.CharField()
    start_datetime = serializers.DateTimeField()
    end_datetime   = serializers.DateTimeField()
    location       = serializers.SerializerMethodField()
    featured_image = serializers.SerializerMethodField()
    tickets_sold   = serializers.SerializerMethodField()
    total_listed   = serializers.SerializerMethodField()
    revenue        = serializers.SerializerMethodField()
    views_count          = serializers.IntegerField()
    saves_count           = serializers.IntegerField()
 
    def get_category(self, obj):
        cat = getattr(obj, "category", None)
        return cat.name if cat else None
 
    def get_location(self, obj):
        loc = getattr(obj, "event_location", None)
        if not loc:
            return None
        return f"{loc.address}{loc.city}, {loc.state}"
 
    def get_featured_image(self, obj):
        media = obj.media.filter(is_featured=True).first()
        return media.image_url if media else None
 
    def get_tickets_sold(self, obj):
        return getattr(obj, "tickets_sold", None) or 0
 
    def get_total_listed(self, obj):
        return getattr(obj, "total_listed", None) or 0
 
    def get_revenue(self, obj):
        val = getattr(obj, "revenue", None)
        return str(val) if val else "0.00"
 
 
# ── Host Chart ────────────────────────────────────────────────────────────────
 
class AdminHostChartPointSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.FloatField()
 

class GiftBadgeSerializer(serializers.Serializer):
    host_id = serializers.IntegerField()