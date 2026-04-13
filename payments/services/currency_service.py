# payments/services/currency_service.py
import requests
from decimal import Decimal
from django.core.cache import cache
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

class CurrencyService:
    """
    Handles dynamic currency conversion using a real API.
    Caches rates to reduce API calls.
    """

    CACHE_TIMEOUT = 3600  # 1 hour

    @staticmethod
    def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
        """Get live exchange rate. Base is always NGN for your plans."""
        if from_currency == to_currency:
            return Decimal("1.00")

        cache_key = f"exchange_rate_{from_currency}_{to_currency}"
        rate = cache.get(cache_key)

        if rate is not None:
            return Decimal(str(rate))

        try:
            # Option 1: Use a good free/paid API (recommended: exchangerate-api.com, currencyfreaks, or openexchangerates)
            # Example using exchangerate-api.com (replace with your API key)
            api_key = settings.CURRENCY_API_KEY  # Add this to your settings.py
            url = f"https://v6.exchangerate-api.com/v6/{api_key}/pair/NGN/{to_currency}"

            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("result") == "success":
                rate = Decimal(str(data["conversion_rate"]))
                cache.set(cache_key, float(rate), timeout=CurrencyService.CACHE_TIMEOUT)
                return rate

        except Exception as e:
            logger.error(f"Failed to fetch exchange rate {from_currency}->{to_currency}: {e}")

        
        logger.warning(f"Using fallback rate for {to_currency}")
        fallback_rates = {"USD": Decimal("0.00062"), "GHS": Decimal("0.0092"), "KES": Decimal("0.082")}
        return fallback_rates.get(to_currency, Decimal("1.00"))

    @staticmethod
    def convert_to_currency(amount_ngn: Decimal, target_currency: str) -> Decimal:
        """Convert NGN amount to target currency using live rate."""
        rate = CurrencyService.get_exchange_rate("NGN", target_currency.upper())
        converted = amount_ngn / rate
        return converted.quantize(Decimal("0.01"))