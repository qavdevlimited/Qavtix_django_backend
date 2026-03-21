from django.contrib.auth import get_user_model
from rest_framework import serializers
from public.models import Category
from host.models import Host
from attendee.models import Attendee
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError

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
    business_type = serializers.CharField(required=False, allow_blank=True)
    registration_number = serializers.CharField(required=False, allow_blank=True)
    tax_id = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(max_length=5000)
    phone_number = serializers.CharField()
    country = serializers.CharField()
    state = serializers.CharField()
    city = serializers.CharField()
    postal_code = serializers.CharField(required=False, allow_blank=True)
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

    def validate(self, data):
        optional_fields = ["business_type", "registration_number", "tax_id", "postal_code"]

        for field in optional_fields:
            if field in data and data[field] == "":
                data[field] = None

        return data

    def create(self, validated_data):
        categories = validated_data.pop("categories", [])
        email = validated_data.pop("email")
        password = validated_data.pop("password")

        try:
            user = User.objects.create_user(
                email=email,
                username=email,
                password=password
            )
        except IntegrityError:
            raise serializers.ValidationError({
                "detail": "Registration failed. If you already have an account, please login."
            })

        host = Host.objects.create(user=user, **validated_data)
        host.categories.set(categories)

        return user
    



class AttendeeRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    full_name = serializers.CharField()
    agree_to_terms = serializers.BooleanField()

    def validate_email(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Registration failed. If you already have an account, please login.")
        return value

    def create(self, validated_data):

        email = validated_data.pop("email")
        password = validated_data.pop("password")
        try:
            user = User.objects.create_user(
                email=email,
                username=email,
                password=password
            )
        except IntegrityError:
            raise serializers.ValidationError({
                "email": "Registration failed. If you already have an account, please login."
            })

        attendee = Attendee.objects.create(user=user, **validated_data)

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