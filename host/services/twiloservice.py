import os
import logging
from twilio.rest import Client
from decouple import config

from host.services.brevoservice import CampaignError

logger = logging.getLogger(__name__)

class TwilioService:
    @staticmethod
    def send_single_sms(recipient, message, sender=None,host=None,data=None):
        """
        Sends a single SMS via Twilio.
        """
        from host.services.campaign_quota_service import CampaignQuotaService, QuotaExceededError

        try:
            CampaignQuotaService.consume_sms_quota(host, count=1)
        except QuotaExceededError as e:
            raise CampaignError(e.message, e.status)

        account_sid = config('TWILIO_ACCOUNT_SID')
        auth_token = config('TWILIO_AUTH_TOKEN')
        default_from =config('TWILIO_PHONE_NUMBER') or '+16626399662'

        # Fallback logic: Use provided sender name, else Twilio number
        from_number = default_from

        try:
            client = Client(account_sid, auth_token)
            sent_message = client.messages.create(
                body=message,
                from_=from_number,
                to=recipient
            )
            return sent_message.sid
        except Exception as exc:
            logger.exception("SMS send failed: %s", exc)
            raise CampaignError(f"Failed to send SMS. Please try again.", 500)