from django.urls import path,include
from .views import *

urlpatterns = [
    path('dashboard/',TicketDashboardView.as_view(),name="attendeee_dashboard"),
    path('favorite/add/',AddFavoriteEventView.as_view(),name="addfavorite"),
    path('favorite/remove/<uuid:event_id>/',RemoveFavoriteEventView.as_view(),name='remove-favorite-event'),
    path('favorite/list/',FavoriteEventListView.as_view(),name="listfave"),
    path("tickets/transfer/",TransferTicketView.as_view(),name="transfer-ticket"),
    path("affliate/dashboard/",AffiliateDashboardView.as_view(),name="affliate_dashboard"),
    path('affliate/event/',AffiliateEventsView.as_view(),name="affliate_event"),
    path('affliate/graph/',AffiliateGraphView.as_view(),name="affliate_graph"),
    path('affliate/earning/history/',AffiliateEarningHistoryView.as_view(),name="earning_history"),
    path('affliate/enroll/',GenerateAffiliateLinkView.as_view(),name="glink"),

    path('withdrawal/request/',RequestWithdrawalView.as_view(),name="request_withdrawal"),
    path('withdrawal/history/',WithdrawalHistoryView.as_view(),name="withdrawal_history"),
    path('payment/list/',PayoutInformationListView.as_view(),name="payment_list"),


]





