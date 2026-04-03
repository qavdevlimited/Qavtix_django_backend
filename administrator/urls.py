from django.urls import path


from administrator.views import AdminActivityView, AdminAffiliateCardsView, AdminAffiliateListView, AdminCustomerCardsView, AdminCustomerListView, AdminDashboardView, AdminLoginView, AdminOTPVerifyView, AdminRevenueView, AdminTicketAnalyticsView, AdminWithdrawalListView


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

]


