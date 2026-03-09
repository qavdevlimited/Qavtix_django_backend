from rest_framework import serializers, status



class AdminLoginSerializer(serializers.Serializer):
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class AdminOTPVerifySerializer(serializers.Serializer):
    temp_token = serializers.UUIDField()
    otp        = serializers.CharField(min_length=6, max_length=6)

