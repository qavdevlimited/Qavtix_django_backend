from django.urls import path,include
from .views import TicketDashboardView,AddFavoriteEventView,FavoriteEventListView,RemoveFavoriteEventView,TransferTicketView

urlpatterns = [
    path('dashboard/',TicketDashboardView.as_view(),name="attendeee_dashboard"),
    path('favorite/add/',AddFavoriteEventView.as_view(),name="addfavorite"),
    path(
        'favorite/remove/<uuid:event_id>/',
        RemoveFavoriteEventView.as_view(),
        name='remove-favorite-event'
    ),
    path('favorite/list/',FavoriteEventListView.as_view(),name="listfave"),
    path(
    "tickets/transfer/",
    TransferTicketView.as_view(),
    name="transfer-ticket"
)
]





