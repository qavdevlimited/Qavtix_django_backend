from django.conf import settings
from django.db import models


class NotificationSettings(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_settings"
    )

    # -------------------------
    # 📧 EMAIL NOTIFICATIONS
    # -------------------------
    email_order_confirmations = models.BooleanField(default=True)
    email_ticket_delivery = models.BooleanField(default=True)
    email_event_reminders = models.BooleanField(default=False)  # 24h before
    email_price_drop_alerts = models.BooleanField(default=False)
    email_similar_events = models.BooleanField(default=False)
    email_weekly_digest = models.BooleanField(default=False)
    email_promotional_offers = models.BooleanField(default=False)
    email_account_security = models.BooleanField(default=True)

    # -------------------------
    # 📱 SMS NOTIFICATIONS
    # -------------------------
    sms_order_confirmations = models.BooleanField(default=False)
    sms_event_reminders = models.BooleanField(default=False)
    sms_promotional_offers = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} Notification Settings"