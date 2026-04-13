from django.urls import path
from payments.views import (
    AddCardConfirmView,
    AddCardInitiateView,
    AttendeeCancelSubscriptionView,
    AttendeeCompleteSubscriptionView,
    AttendeeSubscribeInitiateView,
    CancelSubscriptionView,
    CardCheckoutView,
    CardListView,
    CheckoutView,
    CompleteCheckoutView,
    CompleteSubscriptionView,
    CurrentSubscriptionView,
    HostPlanListView,
    PaystackWebhookView,
    SetDefaultCardView,
    DeleteCardView,
    SplitPayView,
    SubscribeInitiateView,
    SubscriptionHistoryView,
    ActivateFreeTrialView
)
from transactions.views import CompleteFeaturedView, FeaturedInitiateView, FeaturedPlanListView


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


    path("featured/plans/",     FeaturedPlanListView.as_view()),
    path("featured/initiate/",  FeaturedInitiateView.as_view()),
    path("featured/complete/",  CompleteFeaturedView.as_view()),


    path("plans/",            HostPlanListView.as_view()),
    path("plans/current/",    CurrentSubscriptionView.as_view()),
    path("plans/history/",    SubscriptionHistoryView.as_view()),
    path("plans/subscribe/",  SubscribeInitiateView.as_view()),
    path("plans/complete/",   CompleteSubscriptionView.as_view()),
    path("plans/cancel/", CancelSubscriptionView.as_view()),
    path('plans/free-trial/', ActivateFreeTrialView.as_view(), name='free-trial'),


    path('attendee-plans/subscribe/', AttendeeSubscribeInitiateView.as_view(), name='attendee-subscribe'),
    path('attendee-plans/complete/', AttendeeCompleteSubscriptionView.as_view(), name='attendee-complete'),
    path('attendee-plans/cancel/', AttendeeCancelSubscriptionView.as_view(), name='attendee-cancel'),
]