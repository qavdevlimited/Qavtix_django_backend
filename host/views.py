from rest_framework import generics, permissions, status
from events.models import Event
from .serializers import EventSerializer,EventCardSerializer,EventTableSerializer
from public.response import flatten_errors,api_response
from django.http import Http404
from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend
from django.http import Http404
from .utils import EventDashboardFilter
from .permissions import IsEventOwner



class EventCreateView(generics.CreateAPIView):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        # pass request to serializer so it can access user
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context
   
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=False)  
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)
        self.perform_create(serializer)
        return api_response(
            message="Event created successfully",
            status_code=201,
            data=serializer.data
        )
    

class EventUpdateView(generics.UpdateAPIView):
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticated,IsEventOwner]
    lookup_field = "id"   

    def get_queryset(self):
        # Only allow host to update their own events
        user = self.request.user

        if not hasattr(user, "host_profile"):
            return Event.objects.none()

        return Event.objects.filter(host=user.host_profile)

    def update(self, request, *args, **kwargs):
        partial = True  # This allows updating only provided fields
        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=partial
        )

        if not serializer.is_valid():
            return api_response(
                message=serializer.errors,
                status_code=400
            )

        self.perform_update(serializer)

        return api_response(
            message="Event updated successfully",
            status_code=200,
            data=serializer.data
        )


class EventDashboardView(generics.ListAPIView):
    serializer_class = EventTableSerializer
    permission_classes = [permissions.IsAuthenticated]

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    filterset_class = EventDashboardFilter
    search_fields = ["title"]
    ordering_fields = ["title", "start_datetime", "created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        user = self.request.user

        if not hasattr(user, "host_profile"):
            raise Http404("You are not a host or have no events.")

        return Event.objects.filter(host=user.host_profile)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        # ---- Card Counts ----
        base_queryset = Event.objects.filter(host=request.user.host_profile)

        card_data = {
            "live": base_queryset.filter(status="active").count(),
            "draft": base_queryset.filter(status="draft").count(),
            "ended": base_queryset.filter(status="ended").count(),
            "sold_out": base_queryset.filter(status="sold-out").count(),
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated_response = self.get_paginated_response(serializer.data)
            paginated_response.data["cards"] = card_data
            return paginated_response

        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="Event created successfully",
            status_code=201,
            data={
            "cards": EventCardSerializer(card_data).data,
            "table": table_serializer.data
        }
        )