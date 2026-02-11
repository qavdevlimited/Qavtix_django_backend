from django.contrib.auth import get_user_model
from rest_framework import serializers
from public.models import Category
from host.models import Host
from attendee.models import Attendee
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password

User = get_user_model()

class CustomLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(email=attrs['email'], password=attrs['password'])
        if not user:
            raise serializers.ValidationError("Invalid credentials")
        if not user.is_active:
            raise serializers.ValidationError("Account disabled")
        attrs['user'] = user
        return attrs

class HostRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    full_name = serializers.CharField()
    business_name = serializers.CharField()
    business_type = serializers.CharField()
    registration_number = serializers.CharField()
    tax_id = serializers.CharField()
    phone_number = serializers.CharField()
    companies_email = serializers.EmailField()
    country = serializers.CharField()
    state = serializers.CharField()
    city = serializers.CharField()
    postal_code = serializers.CharField()
    categories = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Category.objects.all(), required=False
    )
    relevant_links = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField()
        ),
        required=False,
        allow_empty=True
    )
    agree_to_terms = serializers.BooleanField()

    def create(self, validated_data):
        categories = validated_data.pop("categories", [])

        email = validated_data.pop("email")
        password = validated_data.pop("password")

        user = User.objects.create_user(
            email=email,
            username=email,
            password=password
        )

        host = Host.objects.create(user=user, **validated_data)
        host.categories.set(categories)

        return user



class AttendeeRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    full_name = serializers.CharField()
    phone_number = serializers.CharField()
    country = serializers.CharField()
    state = serializers.CharField()
    city = serializers.CharField()
    categories = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Category.objects.all(), required=False
    )
    agree_to_terms = serializers.BooleanField()

    def create(self, validated_data):
        categories = validated_data.pop("categories", [])

        email = validated_data.pop("email")
        password = validated_data.pop("password")

        user = User.objects.create_user(
            email=email,
            username=email,
            password=password
        )

        attendee = Attendee.objects.create(user=user, **validated_data)
        attendee.categories.set(categories)

        return user



class EmailLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(email=attrs['email'], password=attrs['password'])
        if not user:
            raise serializers.ValidationError("Invalid credentials")
        attrs['user'] = user
        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyPasswordResetOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(max_length=6)


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    new_password = serializers.CharField(min_length=8)

    def validate_new_password(self, value):
        validate_password(value)
        return value