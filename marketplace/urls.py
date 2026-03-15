# marketplace/urls.py
from django.urls import path
from .views import MarketListingCreateView, MarketListingListView, MarketListingDeleteView,MarketListingDetailView

urlpatterns = [
    path("create/", MarketListingCreateView.as_view(), name="marketplace-create"),
    path("list/", MarketListingListView.as_view(), name="marketplace-list"),
    path("delete/<int:pk>/", MarketListingDeleteView.as_view(), name="marketplace-delete"),
    path(
    "marketplace/<int:pk>/",
    MarketListingDetailView.as_view(),
    name="marketplace-detail",
),
]