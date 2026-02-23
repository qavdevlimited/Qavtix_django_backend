# marketplace/urls.py
from django.urls import path
from .views import MarketListingCreateView, MarketListingListView, MarketListingDeleteView

urlpatterns = [
    path("create/", MarketListingCreateView.as_view(), name="marketplace-create"),
    path("list/", MarketListingListView.as_view(), name="marketplace-list"),
    path("delete/<uuid:pk>/", MarketListingDeleteView.as_view(), name="marketplace-delete"),
]