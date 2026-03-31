from django.shortcuts import render
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from events.models import Event,EventLocation
from rest_framework import generics, permissions,status,filters
from django.utils import timezone
from django.db.models import Q

from payments.services.currency_utils import get_currency_for_event
from public.filters import CategoryEventFilter, EventFilter, SearchFilter
from transactions.models import IssuedTicket
from .serializers import CategoryPageSerializer, CategorySerializer, CategorySubscriptionSerializer, EventListSerializer, LocationPageSerializer, LocationSubscriptionSerializer, PromoCodeValidateSerializer,TrendingHostSerializer,FollowActionSerializer,HostPublicDetailSerializer,MessageSerializer, event_list_queryset
from rest_framework.response import Response
from rest_framework.views import APIView, PermissionDenied
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
from host.serializers import EventDetailsSerializer, EventSerializer
from django.shortcuts import get_object_or_404
from .models import Category, CategorySubscription, Follow, LocationSubscription,Message
from attendee.models import AffiliateLink
from .helpers import increment_event_views
from django_filters.rest_framework import DjangoFilterBackend
from .utils import pagination_data
from django.db.models import Exists, OuterRef, Value, BooleanField
from decimal import Decimal


# ── Nearby Events ──────────────────────────────────────────────────────────────

class NearbyEventsView(generics.ListAPIView):
    serializer_class   = EventListSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends    = [DjangoFilterBackend]
    filterset_class    = EventFilter  

    def get_queryset(self):
        user = self.request.user
        now  = timezone.now()

        base = Event.objects.filter(status="active", start_datetime__gte=now)

        if user.is_authenticated and hasattr(user, "profile"):
            user_city = getattr(user.profile, "city", None)
            if user_city:
                base = base.filter(event_location__city__iexact=user_city)

        category   = self.request.query_params.get("category")
        start_date = self.request.query_params.get("start_date")
        end_date   = self.request.query_params.get("end_date")

        if category:
            base = base.filter(category_id=category)
        if start_date and end_date:
            base = base.filter(
                start_datetime__date__gte=start_date,
                end_datetime__date__lte=end_date,
            )

        # Apply N+1 fix
        return event_list_queryset(base).order_by("start_datetime")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page     = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Nearby events retrieved successfully",
                status_code=200,
                data={
                    **pagination_data(self.paginator),
                    "results": serializer.data,
                },
            )

        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="Nearby events retrieved successfully",
            status_code=200,
            data=serializer.data,
        )


# ── Featured Events ────────────────────────────────────────────────────────────

class FeaturedEventsView(generics.ListAPIView):
    serializer_class   = EventListSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends    = [DjangoFilterBackend]
    filterset_class    = EventFilter  

    def get_queryset(self):
        now  = timezone.now()
        base = Event.objects.filter(
            featured__status="active",
            featured__start_date__lte=now,
            featured__end_date__gte=now,
        ).distinct()

        # Apply N+1 fix
        return event_list_queryset(base).order_by("-featured__start_date")

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page     = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Featured events retrieved successfully",
                status_code=200,
                data={
                    **pagination_data(self.paginator),
                    "results": serializer.data,
                },
            )

        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="Featured events retrieved successfully",
            status_code=200,
            data=serializer.data,
        )


# ── Top Event Locations ────────────────────────────────────────────────────────
# No serializer change needed — pure annotation, no N+1 here

class TopEventLocationsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        top_locations = (
            EventLocation.objects
            .filter(
                event__status="active",
                event__start_datetime__gte=timezone.now(),
            )
            .values("city", "state", "country")
            .annotate(event_count=Count("event"))
            .order_by("-event_count")[:10]
        )

        return api_response(
            message="Top event locations retrieved successfully",
            status_code=200,
            data=list(top_locations),
        )


# ── Trending Events ────────────────────────────────────────────────────────────

class TrendingEventsView(generics.ListAPIView):
    serializer_class   = EventListSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends    = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = EventDashboardFilter
    search_fields   = ["title"]

    def get_queryset(self):
        now  = timezone.now()
        base = Event.objects.filter(status="active")

        location   = self.request.query_params.get("location")
        category   = self.request.query_params.get("category")
        min_price  = self.request.query_params.get("min_price")
        max_price  = self.request.query_params.get("max_price")
        start_date = self.request.query_params.get("start_date")
        end_date   = self.request.query_params.get("end_date")

        if location:
            base = base.filter(event_location__city__iexact=location)
        if category:
            base = base.filter(category_id=category)
        if min_price:
            base = base.filter(tickets__price__gte=min_price)
        if max_price:
            base = base.filter(tickets__price__lte=max_price)
        if start_date and end_date:
            base = base.filter(
                start_datetime__date__gte=start_date,
                end_datetime__date__lte=end_date,
            )

        base = base.distinct()

        # Trend score annotations
        base = (
            base
            .annotate(
                total_tickets=Coalesce(Sum("tickets__quantity"), Value(0)),
                sold_tickets=Coalesce(Sum("tickets__sold_count"), Value(0)),
            )
            .annotate(
                sold_percentage=ExpressionWrapper(
                    F("sold_tickets") * 100.0 / NullIf(F("total_tickets"), 0),
                    output_field=FloatField(),
                )
            )
            .annotate(
                trend_score=Coalesce(F("sold_percentage"), Value(0.0)) + Case(
                    When(created_at__gte=now - timedelta(days=7), then=Value(5.0)),
                    default=Value(0.0),
                    output_field=FloatField(),
                )
            )
            .order_by("-trend_score", "-views_count")
        )

        # Apply N+1 fix on top of the annotated queryset
        return event_list_queryset(base)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page     = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Trending events retrieved successfully",
                status_code=200,
                data={
                    **pagination_data(self.paginator),
                    "results": serializer.data,
                },
            )

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
        user = self.request.user

        queryset = Host.objects.all()

        # Filter hosts who have events in this location
        if location:
            queryset = queryset.filter(hoster__status="active", hoster__location__city__iexact=location)

        if user.is_authenticated:
            follow_subquery = Follow.objects.filter(
                user=user,
                host=OuterRef("pk")
            )

            queryset = queryset.annotate(
                is_following=Exists(follow_subquery)
            )
        else:
            queryset = queryset.annotate(
                is_following=Value(False, output_field=BooleanField())
            )

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



class LocationPageView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class   = LocationPageSerializer
    filter_backends    = [DjangoFilterBackend]
    filterset_class    = EventFilter

    def get_queryset(self):
        return Event.objects.filter(status="active").select_related(
            "category",
            "event_location",
            "host",
        ).prefetch_related(
            "tickets",
            "media",
            "tags",
            "social_links",
            "permissions",
        )

    def get(self, request, city):
        city_name = city.strip().title()

        events      = self.filter_queryset(
            self.get_queryset().filter(event_location__city__iexact=city_name)
        )

        events_list       = list(events)   # evaluate once, reused everywhere
        total_events      = len(events_list)
        total_subscribers = LocationSubscription.objects.filter(city__iexact=city_name).count()

        data = {
            "city":              city_name,
            "description":       f"All events happening in {city_name}.",
            "total_events":      total_events,
            "total_subscribers": total_subscribers,
            "events":            events_list,
        }

        serializer = self.get_serializer(data)
        return api_response(message=f"Location page for {city_name}", status_code=200, data=serializer.data)


class SubscribeLocationView(generics.GenericAPIView):
    serializer_class = LocationSubscriptionSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        city  = request.data.get("city")
        email = request.data.get("email")

        if not city:
            return api_response(message="City is required", status_code=400, data={})
        if not email:
            return api_response(message="Email is required", status_code=400, data={})

        city = city.strip().title()

        subscription, created = LocationSubscription.objects.get_or_create(
            city=city,
            email=email
        )

        msg = f"Subscribed to {city} successfully" if created else f"{email} is already subscribed to {city}"
        serializer = self.get_serializer(subscription)
        return api_response(message=msg, status_code=200, data=serializer.data)




class SubscribeCategoryView(generics.GenericAPIView):
    serializer_class = CategorySubscriptionSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        category_id = request.data.get("category")
        email = request.data.get("email")

        if not category_id:
            return api_response("Category is required", 400)

        if not email:
            return api_response("Email is required", 400)

        try:
            category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            return api_response("Category not found", 404)

        subscription, created = CategorySubscription.objects.get_or_create(
            category=category,
            email=email
        )

        msg = "Subscribed successfully" if created else "Already subscribed"

        serializer = CategorySubscriptionSerializer(subscription)

        return api_response(msg, 200, serializer.data)
    



class CategoryPageView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class   = CategoryPageSerializer
    filter_backends    = [DjangoFilterBackend]
    filterset_class    = EventFilter

    def get_queryset(self):
        return Event.objects.filter(status="active").select_related(
            "category",
            "event_location",
            "host",
        ).prefetch_related(
            "tickets",
            "media",
            "tags",
            "social_links",
            "permissions",
        )

    def get(self, request, category_name):
        category = get_object_or_404(Category, name__iexact=category_name)

        # Base queryset scoped to this category, then additional filters on top
        events = self.filter_queryset(
            self.get_queryset().filter(category=category)
        )

        events_list       = list(events)
        total_events      = len(events_list)
        total_subscribers = CategorySubscription.objects.filter(category=category).count()

        data = {
            "name":              category.name,
            "description":       category.description,
            "total_events":      total_events,
            "total_subscribers": total_subscribers,
            "events":            events_list,
        }

        serializer = self.get_serializer(data)
        return api_response(message="Category page retrieved successfully", status_code=200, data=serializer.data)



class SearchEventsView(generics.ListAPIView):
    serializer_class = EventListSerializer
    permission_classes = [permissions.AllowAny]

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    filterset_class = SearchFilter

    search_fields = [
        "title",
        "short_description",
        "event_location__city",
        "event_location__state",
        "event_location__country",
    ]

    ordering_fields = [
        "start_datetime",
        "created_at",
        "views_count",
    ]
    ordering = ["-created_at"]

    def get_queryset(self):
        now = timezone.now()

        base = Event.objects.filter(
            status="active",
            start_datetime__gte=now
        ).distinct()

        return event_list_queryset(base)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page     = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return api_response(
                message="Search results retrieved successfully",
                status_code=200,
                data={
                    **pagination_data(self.paginator),
                    "results": serializer.data,
                },
            )

        serializer = self.get_serializer(queryset, many=True)
        return api_response(
            message="Search results retrieved successfully",
            status_code=200,
            data=serializer.data,
        )



class CancelIssuedTicketView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, ticket_id):
        ticket = get_object_or_404(
            IssuedTicket.objects.select_related("owner", "event"),
            id=ticket_id
        )

    
        if ticket.owner_id != request.user.id:
            raise PermissionDenied("You cannot cancel this ticket.")


        if ticket.status in ["cancelled", "used"]:
            return api_response(
                message=f"Ticket already {ticket.status}",
                status_code=400,
                data=None
            )

        ticket.status = "cancelled"
        ticket.save(update_fields=["status"])

        return api_response(
            message="Ticket cancelled successfully",
            status_code=200,
            data={
                "ticket_id": str(ticket.id),
                "status": ticket.status
            }
        )


class ValidatePromoCodeView(APIView):
    """
    POST /payments/promo/validate/

    Validates a promo code for specific tickets in an event.
    Returns discount details and validity information.
    Useful for real-time promo validation on the frontend (checkout page).
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Validate Promo Code",
        description="Checks if a promo code is valid for the selected tickets and returns discount info.",
        request=PromoCodeValidateSerializer,
        responses={
            200: OpenApiResponse(description="Promo code is valid"),
            400: OpenApiResponse(description="Invalid promo code or not applicable"),
        },
        examples=[
            OpenApiExample(
                "Validate promo code",
                value={
                    "event_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "promo_code": "VIP20",
                    "tickets": [
                        {"ticket_id": 5, "quantity": 2},
                        {"ticket_id": 6, "quantity": 1}
                    ]
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = PromoCodeValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        event_id = data["event_id"]
        promo_code_str = data["promo_code"].strip()
        ticket_items = data["tickets"]

        try:
            from events.models import Event, Ticket

            event = Event.objects.get(id=event_id)
        except Event.DoesNotExist:
            return api_response(message="Event not found.", status_code=404)

        if not promo_code_str:
            return api_response(message="Promo code is required.", status_code=400)

        total_discount = Decimal("0.00")
        applied_tickets = []

        now = timezone.now()

        for item in ticket_items:
            try:
                ticket = Ticket.objects.get(id=item["ticket_id"], event=event)
            except Ticket.DoesNotExist:
                continue  # skip invalid ticket

            try:
                promo = ticket.promo_codes.get(
                    code=promo_code_str,
                    valid_till__gte=now.date()
                )

                subtotal = item["quantity"] * ticket.price
                discount_amount = (subtotal * promo.discount_percentage / 100).quantize(Decimal("0.01"))

                total_discount += discount_amount

                applied_tickets.append({
                    "ticket_id": ticket.id,
                    "ticket_type": ticket.ticket_type,
                    "quantity": item["quantity"],
                    "original_price": str(ticket.price),
                    "discount_percentage": promo.discount_percentage,
                    "discount_amount": str(discount_amount),
                    "valid_till": promo.valid_till.strftime("%Y-%m-%d"),
                })

            except ticket.promo_codes.model.DoesNotExist:
                continue
            except Exception:
                continue

        if total_discount <= 0:
            return api_response(
                message=f"Promo code '{promo_code_str}' is not valid for any of the selected tickets.",
                status_code=400
            )

        return api_response(
            message="Promo code is valid.",
            status_code=200,
            data={
                'type': 'promo code',
                "code": promo_code_str,
                "percentage": int(total_discount),
                "currency": get_currency_for_event(event), 
                "description": f"Promo code '{total_discount}' off.",
                "applied_tickets": applied_tickets,
                "note": "Discount will be applied only to tickets that have this promo code."
            }
        )