from django.shortcuts import render
from events.models import Event,EventLocation
from rest_framework import generics, permissions,status
from django.utils import timezone
from django.db.models import Q
from .serializers import CategorySerializer, EventListSerializer,TrendingHostSerializer,FollowActionSerializer,HostPublicDetailSerializer,MessageSerializer
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count
from .response import api_response
from rest_framework import generics, permissions
from django.utils import timezone
from django.db.models import Sum, F, FloatField, ExpressionWrapper, Q,When,Case,Value
from django.utils import timezone
from datetime import timedelta
from django.db.models.functions import NullIf,Coalesce
from host.utils import EventDashboardFilter
from host.models import Host
from host.serializers import EventDetailsSerializer
from django.shortcuts import get_object_or_404
from .models import Category, Follow,Message
from attendee.models import AffiliateLink
from .helpers import increment_event_views



class NearbyEventsView(generics.ListAPIView):
    serializer_class = EventListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        user = self.request.user
        now = timezone.now()

        base_queryset = Event.objects.filter(
            status="active",
            start_datetime__gte=now
        )

        # filter by logged-in user's location
        if user.is_authenticated and hasattr(user, "profile"):
            user_city = getattr(user.profile, "city", None)
            if user_city:
                base_queryset = base_queryset.filter(location__city__iexact=user_city)

        # Optional filters
        category = self.request.query_params.get("category")
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if category:
            base_queryset = base_queryset.filter(category_id=category)
        if start_date and end_date:
            base_queryset = base_queryset.filter(
                start_datetime__date__gte=start_date,
                end_datetime__date__lte=end_date
            )

        return base_queryset.order_by("start_datetime")
    
    def list(self, request, *args, **kwargs):
        """Override list to use api_response"""
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="Nearby events retrieved successfully",
            status_code=200,
            data=serializer.data
        )

    


class FeaturedEventsView(generics.ListAPIView):
    serializer_class = EventListSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        now = timezone.now()
        return Event.objects.filter(
            featured__status="active",
            featured__start_date__lte=now,
            featured__end_date__gte=now
        ).distinct().order_by("-featured__start_date")

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="Featured events retrieved successfully",
            status_code=200,
            data=serializer.data
        )


class TopEventLocationsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        top_locations = EventLocation.objects.filter(
            event__status="active",
            event__start_datetime__gte=timezone.now()
        ).values(
            "city", "state", "country"
        ).annotate(
            event_count=Count("event")
        ).order_by("-event_count")[:10]  # top 10 locations

        return api_response(
            message="Top event locations retrieved successfully",
            status_code=200,
            data=list(top_locations)
        )
from rest_framework import generics, permissions, filters
from django_filters.rest_framework import DjangoFilterBackend

class TrendingEventsView(generics.ListAPIView):
    serializer_class = EventListSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = EventDashboardFilter
    search_fields = ["title"]

    def get_queryset(self):
        now = timezone.now()
        queryset = Event.objects.filter(status="active")

        # --- Filters ---
        location = self.request.query_params.get("location")
        category = self.request.query_params.get("category")
        min_price = self.request.query_params.get("min_price")
        max_price = self.request.query_params.get("max_price")
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")

        if location:
            queryset = queryset.filter(location__city__iexact=location)
        if category:
            queryset = queryset.filter(category_id=category)

        # Use subquery-safe price filtering to avoid duplicate rows from JOIN
        if min_price:
            queryset = queryset.filter(tickets__price__gte=min_price)
        if max_price:
            queryset = queryset.filter(tickets__price__lte=max_price)
        if start_date and end_date:
            queryset = queryset.filter(
                start_datetime__date__gte=start_date,
                end_datetime__date__lte=end_date,
            )

        # distinct() prevents duplicate events caused by ticket JOIN
        queryset = queryset.distinct()

        # --- Annotations ---
        queryset = queryset.annotate(
            total_tickets=Coalesce(Sum("tickets__quantity"), Value(0)),
            sold_tickets=Coalesce(Sum("tickets__sold_count"), Value(0)),
        ).annotate(
            # NullIf guards against division by zero
            sold_percentage=ExpressionWrapper(
                F("sold_tickets") * 100.0 / NullIf(F("total_tickets"), 0),
                output_field=FloatField(),
            )
        ).annotate(
            trend_score=Coalesce(F("sold_percentage"), Value(0.0)) + Case(
                When(created_at__gte=now - timedelta(days=7), then=Value(5.0)),
                default=Value(0.0),
                output_field=FloatField(),
            )
        ).order_by("-trend_score", "-views_count")

        return queryset  # ← was missing

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset()) 
        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="Trending events retrieved successfully",
            status_code=200,
            data=serializer.data,
        )



class TrendingHostsView(generics.ListAPIView):
    serializer_class = TrendingHostSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        now = timezone.now()
        location = self.request.query_params.get("location")

        queryset = Host.objects.all()

        # Filter hosts who have events in this location
        if location:
            queryset = queryset.filter(hoster__status="active", hoster__location__city__iexact=location)

        # Annotate totals
        queryset = queryset.annotate(
            events_count=Count("hoster", distinct=True),
            total_tickets_sold=Coalesce(Sum("hoster__tickets__sold_count"), Value(0)),
            total_tickets=Coalesce(Sum("hoster__tickets__quantity"), Value(0)),
        ).annotate(
            sold_percentage = ExpressionWrapper(
                F("total_tickets_sold") * 100.0 / Case(
                    When(total_tickets=0, then=Value(1.0, output_field=FloatField())),
                    default=F("total_tickets"),
                    output_field=FloatField()
                ),
                output_field=FloatField()
            ),
            trending_score=F("sold_percentage") + Case(
                When(hoster__created_at__gte=now - timedelta(days=7), then=Value(5.0)),
                default=Value(0.0),
                output_field=FloatField()
            )
        ).order_by("-trending_score", "-followers").distinct()

        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset()) 
        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="Trending hosts retrieved successfully",
            status_code=200,
            data=serializer.data,
        )


class EventDetailView(generics.RetrieveAPIView):
    serializer_class = EventDetailsSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "id"

    def get_queryset(self):
        # Only allow active events
        return Event.objects.filter(status="active")
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        increment_event_views(instance.id)  # Increment views count safely

        ref_code = request.GET.get("ref")
        if ref_code:
            try:
                link = AffiliateLink.objects.get(code=ref_code, event=instance)
                link.clicks += 1
                link.save()
            except AffiliateLink.DoesNotExist:
                # Ignore if link is invalid
                pass

        return api_response(
            message="Details retrieved successfully",
            status_code=200,
            data=serializer.data,
        )
    


class FollowHostCreateView(generics.CreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FollowActionSerializer

    def create(self, request, host_id=None, *args, **kwargs):
        attendee = request.user
        host = get_object_or_404(Host, id=host_id)

        follow_obj, created = Follow.objects.get_or_create(
            user=attendee,
            host=host
        )

        serializer = self.get_serializer(follow_obj)

        if created:
            return api_response(
                message="Host followed successfully",
                status_code=status.HTTP_201_CREATED,
                data=serializer.data
            )

        return api_response(
            message="You are already following this host",
            status_code=status.HTTP_200_OK,
            data=serializer.data
        )

    

class FollowHostDestroyView(generics.DestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FollowActionSerializer

    def get_object(self):
        attendee = self.request.user
        host_id = self.kwargs.get("host_id")

        return get_object_or_404(
            Follow,
            user=attendee,
            host__id=host_id
        )

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        self.perform_destroy(instance)

        return api_response(
            message="Successfully unfollowed host",
            status_code=status.HTTP_200_OK,
            data=serializer.data
        )
        


class HostPublicDetailView(generics.RetrieveAPIView):
    queryset = Host.objects.all()
    serializer_class = HostPublicDetailSerializer
    lookup_field = "id"

    def get_queryset(self):
        return Host.objects.annotate(
            followers_count=Count("following")  # ← THIS
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        return api_response(
            message="Details retrieved successfully",
            status_code=200,
            data=serializer.data,
        )


class MessageCreateView(generics.CreateAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = MessageSerializer

    def create(self, request, *args, **kwargs):

        # Get message data from the request
        full_name = request.data.get("full_name") 
        email = request.data.get("email")
        message_text = request.data.get("message")

        host_id= request.data.get("host")

        # Get the host
        host = get_object_or_404(Host, id=host_id)

        if not message_text:
            return api_response(
                message="Message content is required",
                status_code=status.HTTP_400_BAD_REQUEST
            )

        # Create the message
        message = Message.objects.create(
            host=host,
            full_name=full_name,
            email=email,
            message=message_text
        )

        # Serialize and return
        serializer = self.get_serializer(message)
        return api_response(
            message="Message sent successfully",
            status_code=status.HTTP_201_CREATED,
            data=serializer.data
        )
    



class CategoryListView(APIView):
    """
    GET /categories/

    Returns all categories. No auth required — used for event creation forms,
    filters, and public listing pages.
    """

    def get(self, request):
        categories = Category.objects.all().order_by("name")
        return api_response(
            message="Categories retrieved successfully",
            status_code=200,
            data=CategorySerializer(categories, many=True).data,
        )