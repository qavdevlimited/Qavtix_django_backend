import os
import logging
from twilio.rest import Client
from decouple import config

logger = logging.getLogger(__name__)

class TwilioService:
    @staticmethod
    def send_single_sms(recipient, message, sender=None):
        """
        Sends a single SMS via Twilio.
        """
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
        except Exception as e:
            logger.exception("Twilio SMS failed to send")
            # Raise a standard Exception with a clean message for your view
            raise Exception(f"SMS Provider Error: {str(e)}")