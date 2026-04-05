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


]


