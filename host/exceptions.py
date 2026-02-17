from rest_framework.exceptions import APIException

class EventBannedException(APIException):
    status_code = 400
    default_detail = "This event is banned and cannot be edited."
    default_code = "event_banned"
