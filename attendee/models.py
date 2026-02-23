from django.db import models
from public.models import Category
from django.conf import settings
from host.models import Affliate
import uuid

class Attendee(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendee_profile"
    )
    full_name=models.CharField(max_length=50)
    phone_number= models.CharField(max_length=16)
    country=models.CharField(max_length=30)
    state=models.CharField(max_length=30)
    city=models.CharField(max_length=30)
    categories = models.ManyToManyField(Category,related_name="attendees", blank=True)
    registration_date=models.DateTimeField(auto_now_add=True)
    agree_to_terms=models.BooleanField(default=False)
    role=models.CharField(max_length=20, default="attendee")
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.full_name



class AffliateEarnings(models.Model):
    affliate=models.ForeignKey(Affliate,on_delete=models.DO_NOTHING)
    attendee=models.ForeignKey(Attendee,on_delete=models.DO_NOTHING)
    earning=models.PositiveIntegerField()
    created_at=models.DateField(auto_now=True)



class FavoriteEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorite_events")
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'event')
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} favorited {self.event.title}"
