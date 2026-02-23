# serializers.py

from rest_framework import serializers
from transactions.models import IssuedTicket


class TicketDashboardSerializer(serializers.ModelSerializer):
    sn = serializers.SerializerMethodField()

    event_name = serializers.CharField(source="event.title", read_only=True)
    category = serializers.CharField(source="event.category.name", read_only=True)

    payment = serializers.CharField(source="order.get_status_display", read_only=True)
    event_status = serializers.CharField(source="event.status", read_only=True)

    event_datetime = serializers.DateTimeField(
        source="event.start_datetime",
        read_only=True
    )

    event_image = serializers.SerializerMethodField()

    ticket_type = serializers.CharField(source="ticket_type.name", read_only=True)
    ticket_id = serializers.CharField(read_only=True)
    ticket_status = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = IssuedTicket
        fields = [
            "sn",
            "id",
            "ticket_id",
            "event_name",
            "event_image",
            "category",
            "payment",
            "event_status",
            "ticket_status",
            "ticket_type",
            "event_datetime",
        ]

    def get_sn(self, obj):
        view = self.context.get("view")

        if view and hasattr(view, "paginator"):
            page = view.paginator.page
            index = list(page.object_list).index(obj)
            return (page.number - 1) * view.paginator.page_size + index + 1

        return 1

    def get_event_image(self, obj):
        featured_media = obj.event.media.filter(is_featured=True).first()

        if featured_media:
            return featured_media.image_url

        first_media = obj.event.media.first()
        return first_media.image_url if first_media else None