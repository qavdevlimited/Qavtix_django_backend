from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.utils.serializer_helpers import ReturnList, ReturnDict
import random

def flatten_errors(errors):
    """
    Convert DRF serializer errors into a single plain string.
    """
    if isinstance(errors, dict):
        messages = []
        for key, value in errors.items():
            if isinstance(value, list):
                messages.append(f"{key}: {', '.join(str(v) for v in value)}")
            else:
                messages.append(f"{key}: {value}")
        return "; ".join(messages)
    elif isinstance(errors, list):
        return "; ".join(str(e) for e in errors)
    return str(errors)


def api_response(message="", status_code=200, data=None):
    """
    Standard API response format.
    """
    if isinstance(message, ValidationError):
        message = flatten_errors(message.detail)
    return Response(
        {
            "message": message,
            "status": status_code,
            "data": data if data else {}
        },
        status=status_code
    )


def flatten_errors_login(errors):
    """
    Recursively flatten DRF ValidationError or ErrorDetail objects
    into a clean, readable string.
    """
    if isinstance(errors, dict) or isinstance(errors, ReturnDict):
        messages = []
        for value in errors.values():
            messages.append(flatten_errors(value))
        return "; ".join(messages)
    elif isinstance(errors, list) or isinstance(errors, ReturnList):
        messages = []
        for item in errors:
            messages.append(flatten_errors(item))
        return "; ".join(messages)
    else:
        # ErrorDetail or simple string
        return str(errors)



def generate_otp(length=6):
    return "".join(str(random.randint(0, 9)) for _ in range(length))




import jwt
import time
import os

def generate_apple_client_secret():
    team_id = os.getenv("APPLE_TEAM_ID")
    client_id = os.getenv("APPLE_CLIENT_ID")
    key_id = os.getenv("APPLE_KEY_ID")
    private_key = os.getenv("APPLE_PRIVATE_KEY").replace("\\n", "\n")

    headers = {
        "kid": key_id
    }

    payload = {
        "iss": team_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + 15777000,  # ~6 months
        "aud": "https://appleid.apple.com",
        "sub": client_id,
    }

    client_secret = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers=headers
    )

    return client_secret



def get_user_display_name(user) -> str:
    """
    Returns the best available name for the user.
    Priority: Host/Attendee full_name > user.first_name > user.email
    """
    if hasattr(user, 'host_profile'):
        full_name = user.host_profile.full_name
        if full_name and full_name.strip():
            return full_name.strip()

    if hasattr(user, 'attendee_profile'):
        full_name = user.attendee_profile.full_name
        if full_name and full_name.strip():
            return full_name.strip()

    # Fallback
    if user.first_name and user.first_name.strip():
        return user.first_name.strip()

    # Last resort
    return user.email.split('@')[0]