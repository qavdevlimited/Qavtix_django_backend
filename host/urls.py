from django.urls import path
from .views import *

urlpatterns = [
    path('events/create/', EventCreateView.as_view(), name='event-create'),
    path("events/<uuid:id>/update/",EventUpdateView.as_view(),name="event-update"),
    path("events/management/", EventDashboardView.as_view(), name="events-dashboard"),

    # GET /customers/
    path("customers/", CustomerListView.as_view(), name="customer-list"),

    # GET /customers/<user_id>/
    path("customers/<int:user_id>/", CustomerDetailView.as_view(), name="customer-detail"),

    path("payouts/list/", ListPayoutAccountsView.as_view(), name="list-payouts"),
    path("payouts/add/", AddPayoutAccountView.as_view(), name="add-payout"),

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

]
