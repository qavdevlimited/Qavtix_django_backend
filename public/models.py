from django.db import models
from django.contrib.auth.models import User
# Create your models here.

class Category(models.Model):
    name=models.CharField(max_length=50)
    description=models.TextField(max_length=200,blank=True)
    

class Follow(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="following_hosts"   
    )
    host = models.ForeignKey(
        "host.Host",
        on_delete=models.CASCADE,
        related_name="following"
    )
    created_at=models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'host'],
                name='unique_attendee_host_follow'
            )
        ]


class Message(models.Model):
    full_name=models.CharField()
    email=models.EmailField()
    message=models.TextField(max_length=200)
    host=models.ForeignKey("host.Host",on_delete=models.DO_NOTHING)



# public/models.py

class LocationSubscription(models.Model):
    city = models.CharField(max_length=100)
    email = models.EmailField()
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("city", "email")  # prevent duplicate subscription by same email

    def __str__(self):
        return f"{self.email} subscribed to {self.city}"
    



class CategorySubscription(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="subscriptions"
    )
    email = models.EmailField()
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["category", "email"],
                name="unique_category_email_subscription"
            )
        ]

    def __str__(self):
        return f"{self.email} subscribed to {self.category.name}"