# events/tasks.py
from celery import shared_task
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

@shared_task
def mark_past_events_as_ended():
    from events.models import Event
    from django.db.models import F

    now = timezone.now()

    updated_count = Event.objects.filter(
        status__in=["active", "sold-out"],
        end_datetime__lt=now,
    ).update(
        status="ended",
        updated_at=now
    )

    if updated_count > 0:
        logger.info(f"✅ Marked {updated_count} event(s) as 'ended'.")
    else:
        logger.debug("No events were due to be marked as ended.")

    return updated_count