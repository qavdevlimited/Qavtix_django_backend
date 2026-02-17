from rest_framework import generics, permissions, status
from events.models import Event
from .serializers import EventSerializer
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from public.response import flatten_errors,api_response

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
        serializer.is_valid(raise_exception=False)  # don't let DRF auto-raise
        if not serializer.is_valid():
            return api_response(message=serializer.errors, status_code=400)
        self.perform_create(serializer)
        return api_response(
            message="Event created successfully",
            status_code=201,
            data=serializer.data
        )