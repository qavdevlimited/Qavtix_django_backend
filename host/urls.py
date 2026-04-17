from django.urls import path
from .views import *

urlpatterns = [
    path('profile/', HostProfileView.as_view(), name='host-profile'),

    path('events/create/', EventCreateView.as_view(), name='event-create'),
    path("events/<uuid:id>/update/",EventUpdateView.as_view(),name="event-update"),
    path("events/management/", EventDashboardView.as_view(), name="events-dashboard"),
    path("events/delete/<uuid:id>/", EventDeleteDraftView.as_view(), name="event-delete-draft"),
    #DOWNLOADS
    path("events/<uuid:event_id>/attendees/", DownloadEventAttendeeView.as_view(), name="download-event-attendees"),
    path("events/<uuid:id>/", EventRetrieveView.as_view(), name="event-detail"),

    # customers
    path("customers/", CustomerListView.as_view(), name="customer-list"),
    path("customers/<int:user_id>/", CustomerDetailView.as_view(), name="customer-detail"),
    path("customers/export/", CustomerCSVExportView.as_view(), name="export-customers"),

    #PAYOUTS/FINANCIALS
    path("payouts/list/", ListPayoutAccountsView.as_view(), name="list-payouts"),
    path("payouts/add/", AddPayoutAccountView.as_view(), name="add-payout"),
    path("payouts/remove/<uuid:payout_id>/", PayoutInformationDeleteView.as_view(), name="delete-payout"),

    path("financial/overview/", HostRevenueOverviewView.as_view(), name="host-revenue-overview"),
    path("withdraw/", HostWithdrawalRequestView.as_view(), name="host-withdrawal-request"),
    path('withdrawal/history/',WithdrawalHistoryView.as_view(),name="withdrawal_history"),

    path("security/change-password/", ChangePasswordView.as_view(),name="change_password"),


    # Promo Code
    path("promo-codes/", PromoCodeListView.as_view(), name="host-promo-code-list"),
    path("promo-codes/create/", PromoCodeCreateView.as_view(), name="host-promo-code-create"),
    path("affiliates/", AffiliateListView.as_view(), name="host-affiliate-list"),


    #EMAIL CAMPAIGNS
    path("campaigns/", EmailCampaignListView.as_view(), name="campaign-list"),
    path("campaigns/send/", EmailCampaignCreateAndSendView.as_view(), name="campaign-send"),
    path("campaigns/send-single/", SingleEmailSendView.as_view(), name="campaign-send-single"),
    path("campaigns/send-single-sms/", SingleSMSSendView.as_view(), name="campaign-send-single-sms"),   

    # CHECK IN SYSTEM
    path("checkin/overview/",  CheckInOverviewView.as_view(),     name="checkin-overview"),
    path("checkin/attendees/", CheckInAttendeeListView.as_view(), name="checkin-attendee-list"),
    path("checkin/scan/",      CheckInScanView.as_view(),         name="checkin-scan"),

    #DAHSBOARD
    path("dashboard/overview/", DashboardOverviewView.as_view(), name="dashboard-overview"),
    path("dashboard/feed/",     DashboardFeedView.as_view(),     name="dashboard-feed"),


    #SALES ANALYTICS
    path("sales/cards/",        SalesCardsView.as_view(),       name="sales-cards"),
    path("sales/graphs/",       SalesGraphsView.as_view(),      name="sales-graphs"),
    path("sales/transactions/", TransactionHistoryView.as_view(), name="sales-transactions"),


    #Privacy and Account
    path('privacy/account/delete/',RequestAccountDeletionView.as_view(),name="account_deletion"),
    path('privacy/data/download/',DownloadMyDataView.as_view(),name="download_data"),
    path('privacy/activity/sharing/',ActivitySharingView.as_view(),name="actsharing"),
    path('privacy/settings/',PrivacySettingsView.as_view(),name="privacy_settings"),


    #plans and subscriptions
    path("subscription/status/", HostSubscriptionStatusView.as_view()),
    path("subscription/renew/", RenewSubscriptionView.as_view()),
    path("auto-renew/toggle/", ToggleAutoRenewView.as_view(), name="toggle_auto_renew"),



    

]
