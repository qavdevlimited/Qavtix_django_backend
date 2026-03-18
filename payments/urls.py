from django.urls import path
from payments.views import (
    AddCardConfirmView,
    AddCardInitiateView,
    CardCheckoutView,
    CardListView,
    CheckoutView,
    CompleteCheckoutView,
    PaystackWebhookView,
    SetDefaultCardView,
    DeleteCardView,
    SplitPayView
)

urlpatterns = [
    path("checkout/",              CheckoutView.as_view()),
    path("complete/",              CompleteCheckoutView.as_view()),
    path("split/pay/<uuid:pay_token>/", SplitPayView.as_view()),
    path("charge-card/",                    CardCheckoutView.as_view()),

    path("webhook/paystack/",               PaystackWebhookView.as_view()),

    # Cards
    path("cards/",                          CardListView.as_view()),
    path("cards/initiate/",                 AddCardInitiateView.as_view()),
    path("cards/confirm/",                  AddCardConfirmView.as_view()),
    path("cards/<uuid:card_id>/default/",   SetDefaultCardView.as_view()),
    path("cards/<uuid:card_id>/",           DeleteCardView.as_view()),


    # path("cards/add/", AddCardView.as_view(), name="add-card"),
    # path("cards/list/", ListCardsView.as_view(), name="list-cards"),
    # path("cards/set-default/", SetDefaultCardView.as_view(), name="set-default-card"),
    # path("cards/delete/", DeleteCardView.as_view(), name="delete-card"),
]