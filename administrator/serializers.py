from rest_framework import serializers, status

from host.models import HostActivity



class AdminLoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class AdminOTPVerifySerializer(serializers.Serializer):
    temp_token = serializers.UUIDField()
    otp        = serializers.CharField(min_length=6, max_length=6)




class RevenueAnalyticsResponseSerializer(serializers.Serializer):
    total_revenue = serializers.FloatField()
    daily_breakdown = serializers.ListField(child=serializers.DictField())


class TicketAnalyticsResponseSerializer(serializers.Serializer):
    total_tickets = serializers.IntegerField()
    ticket_breakdown = serializers.DictField()
    ticket_percentages = serializers.DictField()
    most_purchased_ticket = serializers.CharField(allow_null=True)
    quantity_buckets = serializers.DictField()


class HostActivitySerializer(serializers.ModelSerializer):

    class Meta:
        model = HostActivity
        fields = [
            "id",
            "activity_type",
            "message",
            "metadata",
            "created_at"
        ]