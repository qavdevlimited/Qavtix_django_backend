from django.urls import path
from payments.views import (
    CheckoutPaymentView,
    AddCardView,
    CreatePaystackIntentView,
    ListCardsView,
    SetDefaultCardView,
    DeleteCardView
)

urlpatterns = [
    path("checkout/", CheckoutPaymentView.as_view(), name="checkout-payment"),
    path("create-paystack-intent/", CreatePaystackIntentView.as_view()),
    path("cards/add/", AddCardView.as_view(), name="add-card"),
    path("cards/list/", ListCardsView.as_view(), name="list-cards"),
    path("cards/set-default/", SetDefaultCardView.as_view(), name="set-default-card"),
    path("cards/delete/", DeleteCardView.as_view(), name="delete-card"),
]