from rest_framework.views import exception_handler
from rest_framework import status
from rest_framework.response import Response
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated, PermissionDenied
from authentication.utils import flatten_errors_login  # your helper

def custom_exception_handler(exc, context):
    """
    Global DRF exception handler that wraps errors into a consistent response format.
    """
    # Let DRF handle the default response first
    response = exception_handler(exc, context)

    if response is not None:
        message = response.data

        # If the message is a dict or ErrorDetail, flatten it
        if isinstance(message, dict):
            message = flatten_errors_login(message)
        elif isinstance(message, list):
            message = "; ".join(str(m) for m in message)
        else:
            message = str(message)

        # Handle Authentication / Permission errors specifically
        if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
            status_code = 401
        elif isinstance(exc, PermissionDenied):
            status_code = 403
        else:
            status_code = response.status_code

        response.data = {
            "status": status_code,
            "message": message,
            "data": None
        }

    return response
