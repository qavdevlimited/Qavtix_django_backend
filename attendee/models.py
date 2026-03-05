from django.db import models
from public.models import Category
from django.conf import settings
import uuid
from django.contrib.auth.models import User

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
    email_verified=models.BooleanField(default=False)
    dob=models.DateField(null=True,blank=True)
    gender=models.CharField(max_length=100,blank=True)
    profile_picture=models.URLField(blank=True,null=True)
    show_events_attending = models.BooleanField(default=True)
    show_favorites = models.BooleanField(default=True)


    def __str__(self):
        return self.full_name


class TwoFactorAuths(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="two_factor_auth"
    )
    google = models.BooleanField(default=False)
    facebook = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.email} 2FA"
    

class TicketGroup(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    name = models.CharField(max_length=100)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_groups"
    )

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="GroupMember",
        related_name="ticket_groups"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    

class GroupMember(models.Model):
    group = models.ForeignKey(
        TicketGroup,
        on_delete=models.CASCADE,
        related_name="group_members"
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE
    )

    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("group", "user")

    def __str__(self):
        return f"{self.user.email} - {self.group.name}"
    

class AffiliateLink(models.Model):
    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="affiliate_links")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="affiliate_links")
    code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    clicks = models.PositiveIntegerField(default=0)
    sales = models.PositiveIntegerField(default=0)

    def get_url(self):
        return f"https://yourdomain.com/events/{self.event.id}?ref={self.code}"

    def __str__(self):
        return f"{self.user.username} - {self.event.title}"

class AffliateEarnings(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]
    link = models.ForeignKey(AffiliateLink, on_delete=models.CASCADE, related_name="earnings",null=True)
    attendee=models.ForeignKey(Attendee,on_delete=models.DO_NOTHING)
    status=models.CharField(choices=STATUS_CHOICES,default="pending")
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





class AccountDeletionRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("reviewed", "Reviewed"),
        ("deleted", "Deleted"),
        ("rejected", "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deletion_requests")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.user.email} deletion request ({self.status})"
    



