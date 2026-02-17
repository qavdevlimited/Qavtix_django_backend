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