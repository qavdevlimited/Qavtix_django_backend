from django.urls import path


from administrator.views import  *


urlpatterns = [
    path("admin/login/",        AdminLoginView.as_view(),     name="admin-login"),
    path("admin/login/verify/", AdminOTPVerifyView.as_view(), name="admin-otp-verify"),

    path("admin/dashboard/cards/", AdminDashboardView.as_view(), name="admin-dashboard"),
    path("admin/dashboard/revenue/", AdminRevenueView.as_view(), name="admin-dashboard-revenue"),
    path("admin/dashboard/ticket-analytics/", AdminTicketAnalyticsView.as_view(), name="admin-dashboard-ticket-analytics"),
    path("admin/dashboard/activities/", AdminActivityView.as_view(), name="admin-dashboard-activities"),

    # ── Customers ─────────────────────────────────────────────────────────────
    path("admin/customers/cards/",            AdminCustomerCardsView.as_view(),    name="admin-customer-cards"),
    path("admin/customers/",                  AdminCustomerListView.as_view(),     name="admin-customer-list"),
 
    # ── Affiliates ────────────────────────────────────────────────────────────
    path("admin/affiliates/cards/",           AdminAffiliateCardsView.as_view(),   name="admin-affiliate-cards"),
    path("admin/affiliates/",                 AdminAffiliateListView.as_view(),    name="admin-affiliate-list"),
 
    # ── Withdrawals ───────────────────────────────────────────────────────────
    path("admin/withdrawals/",                AdminWithdrawalListView.as_view(),   name="admin-withdrawal-list"),


    #user details
    # Cards  →  GET /admin/users/<id>/cards/?date_range=month
    path("admin/users/<int:user_id>/cards/",   AdminUserDetailCardsView.as_view(),  name="admin-user-cards"),
 
    # Chart  →  GET /admin/users/<id>/chart/?date_range=month
    path("admin/users/<int:user_id>/chart/",   AdminUserDetailChartView.as_view(),  name="admin-user-chart"),
 
    # Orders →  GET /admin/users/<id>/orders/?date_from=2026-01-01&qty_min=1
    path("admin/users/<int:user_id>/orders/",  AdminUserDetailOrdersView.as_view(), name="admin-user-orders"),
 
    # Profile → GET /admin/users/<id>/profile/
    path("admin/users/<int:user_id>/profile/", AdminUserDetailProfileView.as_view(), name="admin-user-profile"),
 
    # Suspend → POST /admin/users/<id>/suspend/  (toggles — suspend or unsuspend)
    path("admin/users/<int:user_id>/suspend/", AdminUserSuspendView.as_view(),      name="admin-user-suspend"),


    # Cards
    path("admin/hosts/cards/",   AdminHostCardsView.as_view(),            name="admin-host-cards"),
    # List
    path("admin/hosts/",         AdminHostListView.as_view(),              name="admin-host-list"),
    # Pending verifications
    path("admin/hosts/verifications/",                   AdminHostVerificationListView.as_view(), name="admin-host-verifications"),
    path("admin/hosts/<int:host_id>/approve/",           AdminHostApproveView.as_view(),          name="admin-host-approve"),
    path("admin/hosts/<int:host_id>/decline/",           AdminHostDeclineView.as_view(),          name="admin-host-decline"),
 
    # ── Host Detail ───────────────────────────────────────────────────────────
    path("admin/hosts/<int:host_id>/cards/",   AdminHostDetailCardsView.as_view(),   name="admin-host-detail-cards"),
    path("admin/hosts/<int:host_id>/profile/", AdminHostDetailProfileView.as_view(), name="admin-host-detail-profile"),
    path("admin/hosts/<int:host_id>/events/",  AdminHostDetailEventsView.as_view(),  name="admin-host-detail-events"),
    path("admin/hosts/<int:host_id>/chart/",   AdminHostDetailChartView.as_view(),   name="admin-host-detail-chart"),
    path("admin/hosts/<int:host_id>/suspend/", AdminHostSuspendView.as_view(),       name="admin-host-suspend"),

    path("admin/hosts/<int:host_id>/gift-badge/", GiftBadgeView.as_view()),


    # ── Event Management ──────────────────────────────────────────────────────
    path("admin/events/cards/", AdminEventCardsView.as_view(), name="admin-event-cards"),
    path("admin/events/",       AdminEventListView.as_view(),  name="admin-event-list"),
 
    # Event Actions
    path("admin/events/<uuid:event_id>/attendees/",    AdminEventAttendeesView.as_view(),   name="admin-event-attendees"),
    path("admin/events/<uuid:event_id>/ticket-types/", AdminEventTicketTypesView.as_view(), name="admin-event-ticket-types"),
    path("admin/events/<uuid:event_id>/suspend/",      AdminEventSuspendView.as_view(),     name="admin-event-suspend"),
    path("admin/events/<uuid:event_id>/delete/",       AdminEventDeleteView.as_view(),      name="admin-event-delete"),
    path("admin/events/<uuid:event_id>/feature/",      AdminEventFeatureView.as_view(),     name="admin-event-feature"),
 
    # ── Audit Logs ────────────────────────────────────────────────────────────
    path("admin/audit-logs/", AdminAuditLogListView.as_view(), name="admin-audit-logs"),


    # ── Financials ────────────────────────────────────────────────────────────
    path("admin/financials/cards/",          AdminFinancialCardsView.as_view(),      name="admin-financial-cards"),
    path("admin/financials/resale-cards/",   AdminFinancialResaleCardsView.as_view(), name="admin-financial-resale-cards"),
    path("admin/financials/payouts/pending/", AdminPayoutPendingView.as_view(),       name="admin-payout-pending"),
    path("admin/financials/payouts/approved/", AdminPayoutApprovedView.as_view(),     name="admin-payout-approved"),
    path("admin/financials/payouts/approve/",  AdminPayoutApproveView.as_view(),      name="admin-payout-approve"),
    path("admin/financials/payouts/decline/",  AdminPayoutDeclineView.as_view(),      name="admin-payout-decline"),
    path("admin/financials/payout/force/",AdminPayoutForceView.as_view() , name="admin-payout-force"),
    path("admin/financials/marketplace/",      AdminMarketplaceListingsView.as_view(), name="admin-marketplace-listings"),
    path("admin/financials/featured/",         AdminFeaturedPaymentsView.as_view(),   name="admin-featured-payments"),
    path("admin/financials/subscriptions/",    AdminSubscriptionPaymentsView.as_view(), name="admin-subscription-payments"),


    path("admin/config/general/",       AdminConfigGeneralView.as_view(),       name="admin-config-general"),
    path("admin/config/policies/",      AdminConfigPoliciesView.as_view(),      name="admin-config-policies"),
    path("admin/config/fees/",          AdminConfigFeesView.as_view(),          name="admin-config-fees"),
    path("admin/config/fraud/",         AdminConfigFraudView.as_view(),         name="admin-config-fraud"),
    path("admin/config/notifications/", AdminConfigNotificationsView.as_view(), name="admin-config-notifications"),
    path("admin/config/localization/",  AdminConfigLocalizationView.as_view(),  name="admin-config-localization"),
 
    # POST — resets ALL config to factory defaults
    path("admin/config/reset-all/", AdminConfigResetAllView.as_view(), name="admin-config-reset-all"),


    path("admin/profile/", AdminProfileView.as_view(), name="admin-profile"),
]


