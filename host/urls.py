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

    # path('withdrawal/request/',RequestWithdrawalView.as_view(),name="request_withdrawal"),

]
