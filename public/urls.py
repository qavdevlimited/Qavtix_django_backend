from django.contrib import admin
from django.urls import path
from .views import *



urlpatterns = [
   path('events/nearby/',NearbyEventsView.as_view(),name="nearby_events"),
   path('event/featured/',FeaturedEventsView.as_view(),name='featured_events'),
   path('event/top-locations/',TopEventLocationsView.as_view(),name="top_locations"),
   path('event/trending/',TrendingEventsView.as_view(),name="trending_events"),
   path('event/trending-hosts/',TrendingHostsView.as_view(),name="trending_host"),
   path("event/<uuid:id>/", EventDetailView.as_view(), name="event-detail"),

   path("hosts/<int:host_id>/follow/", FollowHostCreateView.as_view()),
   path("hosts/<int:host_id>/unfollow/", FollowHostDestroyView.as_view()),
   path("hosts/<int:id>/", HostPublicDetailView.as_view(),name="host_details"),

   path('message/',MessageCreateView.as_view(),name="create_message"),



    
]





