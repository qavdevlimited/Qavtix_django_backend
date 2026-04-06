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



# ── Event Cards ───────────────────────────────────────────────────────────────

class AdminEventCardSerializer(serializers.Serializer):
    live      = serializers.IntegerField()
    suspended = serializers.IntegerField()
    ended     = serializers.IntegerField()
    sold_out  = serializers.IntegerField()


# ── Event List ────────────────────────────────────────────────────────────────

class AdminEventListSerializer(serializers.Serializer):
    event_id       = serializers.UUIDField(source="id")
    title          = serializers.CharField()
    status         = serializers.CharField()
    category       = serializers.SerializerMethodField()
    featured_image = serializers.SerializerMethodField()
    host_name      = serializers.SerializerMethodField()
    host_id        = serializers.SerializerMethodField()

    # Date/Time
    start_datetime = serializers.DateTimeField()
    end_datetime   = serializers.DateTimeField()

    # Location
    location       = serializers.SerializerMethodField()

    # Stats
    tickets_sold  = serializers.SerializerMethodField()
    total_listed  = serializers.SerializerMethodField()
    revenue       = serializers.SerializerMethodField()
    views_count   = serializers.IntegerField()
    saves_count   = serializers.IntegerField()

    def get_category(self, obj):
        cat = getattr(obj, "category", None)
        return cat.name if cat else None

    def get_featured_image(self, obj):
        media = obj.media.filter(is_featured=True).first()
        return media.image_url if media else None

    def get_host_name(self, obj):
        return getattr(obj.host, "business_name", None) or getattr(obj.host, "full_name", "")

    def get_host_id(self, obj):
        return getattr(obj.host, "id", None)

    def get_location(self, obj):
        loc = getattr(obj, "event_location", None)
        if not loc:
            return None
        return {"city": loc.city, "state": loc.state, "country": loc.country}

    def get_tickets_sold(self, obj):
        return getattr(obj, "tickets_sold", None) or 0

    def get_total_listed(self, obj):
        return getattr(obj, "total_listed", None) or 0

    def get_revenue(self, obj):
        val = getattr(obj, "revenue", None)
        return str(val) if val else "0.00"


# ── Event Attendee List ───────────────────────────────────────────────────────

class AdminEventAttendeeSerializer(serializers.Serializer):
    ticket_id     = serializers.UUIDField(source="id")
    ticket_type   = serializers.SerializerMethodField()
    status        = serializers.CharField()
    purchase_date = serializers.DateTimeField(source="created_at")
    amount        = serializers.SerializerMethodField()
    quantity      = serializers.SerializerMethodField()

    # Attendee info
    attendee_name    = serializers.SerializerMethodField()
    attendee_email   = serializers.SerializerMethodField()
    profile_picture  = serializers.SerializerMethodField()

    def get_ticket_type(self, obj):
        ot = getattr(obj, "order_ticket", None)
        return ot.ticket.ticket_type if ot and ot.ticket else None

    def get_amount(self, obj):
        order = getattr(obj, "order", None)
        return str(order.total_amount) if order else "0.00"

    def get_quantity(self, obj):
        ot = getattr(obj, "order_ticket", None)
        return ot.quantity if ot else 1

    def get_attendee_name(self, obj):
        if obj.owner:
            attendee = getattr(obj.owner, "attendee_profile", None)
            return attendee.full_name if attendee else obj.owner.email
        return obj.guest_email or "Guest"

    def get_attendee_email(self, obj):
        if obj.owner:
            return obj.owner.email
        return obj.guest_email

    def get_profile_picture(self, obj):
        if obj.owner:
            attendee = getattr(obj.owner, "attendee_profile", None)
            return attendee.profile_picture if attendee else None
        return None


# ── Ticket Types for Filter Dropdown ─────────────────────────────────────────

class AdminTicketTypeSerializer(serializers.Serializer):
    id          = serializers.IntegerField()
    ticket_type = serializers.CharField()
    price       = serializers.DecimalField(max_digits=12, decimal_places=2)
    quantity    = serializers.IntegerField()
    sold_count  = serializers.IntegerField()


# ── Feature Event ─────────────────────────────────────────────────────────────

class AdminFeatureEventSerializer(serializers.Serializer):
    plan_slug = serializers.ChoiceField(choices=["basic", "standard", "advanced", "premium"])


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AdminAuditLogSerializer(serializers.Serializer):
    id           = serializers.UUIDField()
    timestamp    = serializers.DateTimeField(source="created_at")
    admin_email  = serializers.EmailField()
    admin_name   = serializers.SerializerMethodField()
    action       = serializers.CharField()
    action_label = serializers.SerializerMethodField()
    details      = serializers.CharField()
    target_type  = serializers.CharField()
    target_id    = serializers.CharField()
    target_label = serializers.CharField()
    ip_address   = serializers.IPAddressField(allow_null=True)
    user_agent   = serializers.CharField()

    def get_admin_name(self, obj):
        if obj.admin:
            profile = getattr(obj.admin, "admin_profile", None)
            return profile.full_name if profile else obj.admin_email
        return obj.admin_email

    def get_action_label(self, obj):
        from administrator.models import AdminAuditLog
        return dict(AdminAuditLog.ACTION_CHOICES).get(obj.action, obj.action)



# ── Financial Cards ───────────────────────────────────────────────────────────
 
class AdminFinancialResaleCardSerializer(serializers.Serializer):
    total_resale_revenue         = serializers.DecimalField(max_digits=14, decimal_places=2)
    net_profit     = serializers.DecimalField(max_digits=14, decimal_places=2)
    tickets_resold = serializers.DecimalField(max_digits=14, decimal_places=2)
    active_listings   = serializers.DecimalField(max_digits=14, decimal_places=2)



class AdminFinancialCardSerializer(serializers.Serializer):
    total_gmv         = serializers.DecimalField(max_digits=14, decimal_places=2)
    platform_fees     = serializers.DecimalField(max_digits=14, decimal_places=2)
    affiliate_balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    pending_payouts   = serializers.DecimalField(max_digits=14, decimal_places=2)
 
 
# ── Payout Request (Pending / Approved) ───────────────────────────────────────
 
class AdminPayoutRequestSerializer(serializers.Serializer):
    payout_id    = serializers.UUIDField(source="id")
    amount       = serializers.DecimalField(max_digits=12, decimal_places=2)
    request_date = serializers.DateTimeField(source="created_at")
    status       = serializers.CharField()
 
    # Seller/Owner — could be host or attendee
    seller = serializers.SerializerMethodField()
 
    # Bank account
    bank_account = serializers.SerializerMethodField()
 
    def get_seller(self, obj):
        from administrator.service.financial_service import AdminPayoutRequestService
        return AdminPayoutRequestService.get_seller_info(obj)
 
    def get_bank_account(self, obj):
        acct = obj.payout_account
        return {
            "account_name":   acct.account_name,
            "account_number": acct.account_number,
            "bank_name":      acct.bank_name,
        }
 
 
# ── Bulk Payout Action ────────────────────────────────────────────────────────
 
class BulkPayoutActionSerializer(serializers.Serializer):
    withdrawal_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
    )
    reason = serializers.CharField(required=False, allow_blank=True, default="")
 
 
# ── Marketplace Listings ──────────────────────────────────────────────────────
 
class AdminMarketplaceListingSerializer(serializers.Serializer):
    ticket_id    = serializers.UUIDField(source="ticket.id")
    listing_id   = serializers.IntegerField(source="id")
    status       = serializers.CharField()
    listing_price = serializers.DecimalField(max_digits=10, decimal_places=2, source="price")
    listing_date  = serializers.DateTimeField(source="created_at")
 
    # Reseller
    reseller = serializers.SerializerMethodField()
 
    # Event
    event = serializers.SerializerMethodField()
 
    def get_reseller(self, obj):
        seller   = obj.seller
        host     = getattr(seller, "host_profile", None)
        attendee = getattr(seller, "attendee_profile", None)
 
        if host:
            return {
                "name":            host.full_name,
                "email":           seller.email,
                "profile_picture": host.profile_picture,
            }
        if attendee:
            return {
                "name":            attendee.full_name or seller.email,
                "email":           seller.email,
                "profile_picture": attendee.profile_picture,
            }
        return {"name": seller.email, "email": seller.email, "profile_picture": None}
 
    def get_event(self, obj):
        event = obj.ticket.event
        cat   = getattr(event, "category", None)
        media = event.media.filter(is_featured=True).first()
        return {
            "id":            str(event.id),
            "title":         event.title,
            "category":      cat.name if cat else None,
            "featured_image": media.image_url if media else None,
        }
 
 
# ── Featured Event Payments ───────────────────────────────────────────────────
 
class AdminFeaturedPaymentSerializer(serializers.Serializer):
    payment_id   = serializers.UUIDField(source="id")
    status       = serializers.CharField()
    package      = serializers.SerializerMethodField()
    amount       = serializers.DecimalField(max_digits=10, decimal_places=2, source="payment_amount")
    payment_date = serializers.DateTimeField(source="start_date")
    payment_method = serializers.CharField()
 
    # Host
    host = serializers.SerializerMethodField()
 
    # Event
    event = serializers.SerializerMethodField()
 
    def get_package(self, obj):
        meta = obj.metadata or {}
        return {
            "slug": meta.get("plan_slug", ""),
            "name": meta.get("plan_name", ""),
            "duration_days": meta.get("duration_days", ""),
        }
 
    def get_host(self, obj):
        host = getattr(obj.user, "host_profile", None)
        return {
            "name":            host.full_name    if host else obj.user.email,
            "email":           obj.user.email,
            "business_name":   host.business_name if host else None,
            "profile_picture": host.profile_picture if host else None,
        }
 
    def get_event(self, obj):
        event = obj.event
        cat   = getattr(event, "category", None)
        media = event.media.filter(is_featured=True).first()
        return {
            "id":             str(event.id),
            "title":          event.title,
            "category":       cat.name if cat else None,
            "featured_image": media.image_url if media else None,
        }
 
 
# ── Subscription Plan Payments ────────────────────────────────────────────────
 
class AdminSubscriptionPaymentSerializer(serializers.Serializer):
    payment_id   = serializers.UUIDField(source="id")
    status       = serializers.CharField()
    plan         = serializers.SerializerMethodField()
    billing_cycle = serializers.CharField()
    timeline     = serializers.SerializerMethodField()
    amount       = serializers.DecimalField(max_digits=10, decimal_places=2, source="amount_paid")
    payment_date = serializers.DateTimeField(source="started_at")
    currency     = serializers.CharField()
 
    # Host profile
    profile = serializers.SerializerMethodField()
 
    def get_plan(self, obj):
        return {
            "slug": obj.plan_slug,
            "name": obj.plan.name if obj.plan else obj.plan_slug,
        }
 
    def get_timeline(self, obj):
        return {
            "started_at": obj.started_at,
            "expires_at": obj.expires_at,
        }
 
    def get_profile(self, obj):
        host = obj.host
        return {
            "name":            host.full_name,
            "email":           host.user.email,
            "business_name":   host.business_name,
            "profile_picture": host.profile_picture,
        }



# ── General ───────────────────────────────────────────────────────────────────

class CurrencySerializer(serializers.Serializer):
    code  = serializers.CharField(max_length=10)
    label = serializers.CharField(max_length=50)


class GeneralConfigSerializer(serializers.Serializer):
    platform_support_email = serializers.EmailField()
    default_currency       = CurrencySerializer()
    default_timezone       = serializers.CharField()


class GeneralConfigUpdateSerializer(serializers.Serializer):
    platform_support_email = serializers.EmailField(required=False)
    default_currency       = CurrencySerializer(required=False)
    default_timezone       = serializers.CharField(required=False)


# ── Policies ──────────────────────────────────────────────────────────────────

class PoliciesConfigSerializer(serializers.Serializer):
    seller_verification_required = serializers.BooleanField()
    auto_approve_listing         = serializers.BooleanField()


class PoliciesConfigUpdateSerializer(serializers.Serializer):
    seller_verification_required = serializers.BooleanField(required=False)
    auto_approve_listing         = serializers.BooleanField(required=False)


# ── Fees ──────────────────────────────────────────────────────────────────────

class FeesConfigSerializer(serializers.Serializer):
    ticket_resell_commission = serializers.IntegerField()
    seller_service_fee       = serializers.IntegerField()
    buyer_service_fee        = serializers.IntegerField()
    vat_enabled              = serializers.BooleanField()
    prices_include_vat       = serializers.BooleanField()


class FeesConfigUpdateSerializer(serializers.Serializer):
    ticket_resell_commission = serializers.IntegerField(required=False, min_value=0, max_value=100)
    seller_service_fee       = serializers.IntegerField(required=False, min_value=0, max_value=100)
    buyer_service_fee        = serializers.IntegerField(required=False, min_value=0, max_value=100)
    vat_enabled              = serializers.BooleanField(required=False)
    prices_include_vat       = serializers.BooleanField(required=False)


# ── Fraud ─────────────────────────────────────────────────────────────────────

class FraudConfigSerializer(serializers.Serializer):
    fraud_sensitivity = serializers.ChoiceField(choices=["low", "medium", "high"])


class FraudConfigUpdateSerializer(serializers.Serializer):
    fraud_sensitivity = serializers.ChoiceField(
        choices=["low", "medium", "high"], required=False
    )


# ── Notifications ─────────────────────────────────────────────────────────────

class NotificationPrefsSerializer(serializers.Serializer):
    admin_alerts      = serializers.BooleanField()
    fraud_alerts      = serializers.BooleanField()
    high_volume_sales = serializers.BooleanField()
    failed_payouts    = serializers.BooleanField()


class NotificationsConfigSerializer(serializers.Serializer):
    email_notifications = NotificationPrefsSerializer()
    sms_notifications   = NotificationPrefsSerializer()


class NotificationsConfigUpdateSerializer(serializers.Serializer):
    email_notifications = NotificationPrefsSerializer(required=False)
    sms_notifications   = NotificationPrefsSerializer(required=False)


# ── Localization ──────────────────────────────────────────────────────────────

class LocalizationConfigSerializer(serializers.Serializer):
    supported_countries  = serializers.ListField(child=serializers.CharField())
    supported_currencies = serializers.ListField(child=serializers.CharField())
    language             = serializers.CharField()
    date_time_format     = serializers.ChoiceField(choices=["12h", "24h"])


class LocalizationConfigUpdateSerializer(serializers.Serializer):
    supported_countries  = serializers.ListField(child=serializers.CharField(), required=False)
    supported_currencies = serializers.ListField(child=serializers.CharField(), required=False)
    language             = serializers.CharField(required=False)
    date_time_format     = serializers.ChoiceField(choices=["12h", "24h"], required=False)


# ── Reset ─────────────────────────────────────────────────────────────────────

class ResetSectionSerializer(serializers.Serializer):
    section = serializers.ChoiceField(
        choices=["general", "policies", "fees", "fraud", "notifications", "localization"],
        required=False,
    )