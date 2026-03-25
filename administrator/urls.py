from django.urls import path


from administrator.views import AdminActivityView, AdminDashboardView, AdminLoginView, AdminOTPVerifyView, AdminRevenueView, AdminTicketAnalyticsView


urlpatterns = [
    path("admin/login/",        AdminLoginView.as_view(),     name="admin-login"),
    path("admin/login/verify/", AdminOTPVerifyView.as_view(), name="admin-otp-verify"),

    path("admin/dashboard/cards/", AdminDashboardView.as_view(), name="admin-dashboard"),
    path("admin/dashboard/revenue/", AdminRevenueView.as_view(), name="admin-dashboard-revenue"),
    path("admin/dashboard/ticket-analytics/", AdminTicketAnalyticsView.as_view(), name="admin-dashboard-ticket-analytics"),
    path("admin/dashboard/activities/", AdminActivityView.as_view(), name="admin-dashboard-activities"),

]