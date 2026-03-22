# payments/serializers/featured_serializers.py

from rest_framework import serializers


class FeaturedInitiateSerializer(serializers.Serializer):
    event_id   = serializers.UUIDField()
    plan_slug  = serializers.ChoiceField(choices=["basic", "standard", "advanced", "premium"])
    country    = serializers.CharField(default="NG")
    currency   = serializers.CharField(default="NGN")
    card_id    = serializers.UUIDField(required=False, allow_null=True)
    save_card  = serializers.BooleanField(default=False)


class CompleteFeaturedSerializer(serializers.Serializer):
    reference = serializers.CharField()
    save_card = serializers.BooleanField(default=False)
    country   = serializers.CharField(default="NG")