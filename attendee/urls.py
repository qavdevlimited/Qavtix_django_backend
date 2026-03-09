from django.urls import path,include
from .views import *

urlpatterns = [
    path('dashboard/',TicketDashboardView.as_view(),name="attendeee_dashboard"),
    path('favorite/add/',AddFavoriteEventView.as_view(),name="addfavorite"),
    path('favorite/remove/<uuid:event_id>/',RemoveFavoriteEventView.as_view(),name='remove-favorite-event'),
    path('favorite/list/',FavoriteEventListView.as_view(),name="listfave"),
    path("tickets/transfer/",TransferTicketView.as_view(),name="transfer-ticket"),
    path("tickets/<int:issued_ticket_id>/receipt/", TicketReceiptView.as_view(), name="ticket-receipt"),
    path("affliate/dashboard/",AffiliateDashboardView.as_view(),name="affliate_dashboard"),
    path('affliate/event/',AffiliateEventsView.as_view(),name="affliate_event"),
    path('affliate/graph/',AffiliateGraphView.as_view(),name="affliate_graph"),
    path('affliate/earning/history/',AffiliateEarningHistoryView.as_view(),name="earning_history"),
    path('affliate/enroll/',GenerateAffiliateLinkView.as_view(),name="glink"),

    path('withdrawal/request/',RequestWithdrawalView.as_view(),name="request_withdrawal"),
    path('withdrawal/history/',WithdrawalHistoryView.as_view(),name="withdrawal_history"),
    path('payment/list/',PayoutInformationListView.as_view(),name="payment_list"),

    path("profile/", AttendeeProfileView.as_view(), name="attendee-profile"),
    path("profile/update/", UpdateAttendeeProfileView.as_view(), name="update-attendee-profile"),
    path("profile/twofactor/",ToggleTwoFactorView.as_view(),name="toggle_twofactor"),
    path("profile/change-password/", ChangePasswordView.as_view(),name="change_password"),
    path("profile/notifications/settings/", NotificationSettingsView.as_view(), name="notification-settings"),


    path("groups/", MyGroupsView.as_view()),
    path("groups/create/", CreateGroupView.as_view()),
    path("groups/<uuid:group_id>/update/", UpdateGroupView.as_view()),
    path("groups/<uuid:group_id>/delete/", DeleteGroupView.as_view()),
    path("groups/<uuid:group_id>/remove-member/", RemoveGroupMemberView.as_view()),

    path('privacy/activity/sharing/',ActivitySharingView.as_view(),name="actsharing"),
    path('privacy/data/download/',DownloadMyDataView.as_view(),name="download_data"),
    path('privacy/account/delete/',RequestAccountDeletionView.as_view(),name="account_deletion"),

    path("payouts/list/", ListPayoutAccountsView.as_view(), name="list-payouts"),
    path("payouts/add/", AddPayoutAccountView.as_view(), name="add-payout"),


]





