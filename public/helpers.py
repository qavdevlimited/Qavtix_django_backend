from django.db.models import F

def increment_event_views(event_id):
    """
    Call in your public event DETAIL view.
    Uses F() to avoid race conditions under concurrent requests.
    """
    from events.models import Event
    Event.objects.filter(id=event_id).update(views_count=F("views_count") + 1)
