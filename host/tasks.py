# host/tasks.py
from celery import shared_task
from django.utils import timezone
from host.services.RenewSubscriptionService import RenewSubscriptionService, SubscriptionError
from payments.tasks import send_plan_activated_email
from django.core.mail import send_mail

@shared_task
def auto_renew_subscriptions():
    from host.models import HostSubscription
    from datetime import timedelta

    today = timezone.now()
    # Get active subscriptions set to auto-renew and expiring tomorrow
    to_renew = HostSubscription.objects.filter(
        status="active",
        auto_renew=True,
        expires_at__date=today.date() + timedelta(days=1)
    )

    for sub in to_renew:
        user = sub.host.user
        try:
            service = RenewSubscriptionService(user)
            result = service.run()
            # send success email
            send_mail(
                subject="Subscription Renewed Successfully",
                message=f"Hi {user.get_full_name()}, your {sub.plan.name} plan has been renewed successfully. Next expiry: {result['expires_at']}.",
                from_email="no-reply@qavtix.com",
                recipient_list=[user.email],
            )
        except SubscriptionError as e:
            # send failure email
            send_mail(
                subject="Subscription Renewal Failed",
                message=(
                    f"Hi {user.get_full_name()}, we could not renew your {sub.plan.name} plan automatically. "
                    f"Reason: {e.message}. Please update your payment method or disable auto-renew if you wish."
                ),
                from_email="no-reply@qavtix.com",
                recipient_list=[user.email],
            )