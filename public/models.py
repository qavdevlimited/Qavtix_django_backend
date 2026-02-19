from django.db import models
from django.contrib.auth.models import User
# Create your models here.

class Category(models.Model):
    name=models.CharField(max_length=50)
    

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