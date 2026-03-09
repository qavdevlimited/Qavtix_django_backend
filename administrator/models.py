import uuid

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class Admin(models.Model):
    user=models.OneToOneField(User, on_delete=models.CASCADE,related_name='admin_profile')
    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=50,default='admin')
    

    def __str__(self):
        return self.full_name
    


class AdminOTP(models.Model):
    """
    Stores a one-time password for admin two-factor login.
    Created after successful password verification.
    Consumed (marked used) after successful OTP verification.
    """
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(User,on_delete=models.CASCADE,related_name="admin_otps",)
    otp        = models.CharField(max_length=6)

    # Temporary token returned to the client after password check.
    # Client sends this back with the OTP to prove they are
    # continuing the same login session.
    temp_token = models.UUIDField(default=uuid.uuid4, unique=True)

    is_used    = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(minutes=10)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"OTP for {self.user.email} — {'used' if self.is_used else 'pending'}"