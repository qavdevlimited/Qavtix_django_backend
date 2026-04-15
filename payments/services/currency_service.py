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
    Base currency is always NGN.
    """

    CACHE_TIMEOUT = 3600  # 1 hour

    @staticmethod
    def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
        """Get live exchange rate from NGN to target currency."""
        if from_currency.upper() == to_currency.upper():
            print(f"[CurrencyService] Same currency {from_currency} → {to_currency}, rate = 1.00")
            return Decimal("1.00")

        to_currency = to_currency.upper()
        cache_key = f"exchange_rate_{from_currency}_{to_currency}"
        rate = cache.get(cache_key)

        if rate is not None:
            print(f"[CurrencyService] Cache hit for {from_currency}→{to_currency}: {rate}")
            return Decimal(str(rate))

        print(f"[CurrencyService] Fetching live rate for NGN → {to_currency}...")

        try:
            api_key = settings.CURRENCY_API_KEY
            url = f"https://v6.exchangerate-api.com/v6/{api_key}/pair/NGN/{to_currency}"

            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get("result") == "success":
                rate = Decimal(str(data["conversion_rate"]))
                cache.set(cache_key, float(rate), timeout=CurrencyService.CACHE_TIMEOUT)
                
                print(f"[CurrencyService] API Success: 1 NGN = {rate} {to_currency}")
                return rate

            else:
                print(f"[CurrencyService] API returned error: {data.get('error-type', 'Unknown')}")

        except Exception as e:
            print(f"[CurrencyService] ERROR fetching rate NGN→{to_currency}: {e}")

        # Fallback
        print(f"[CurrencyService] Using fallback rate for {to_currency}")
        fallback_rates = {
            "USD": Decimal("0.00060"),   # ≈ ₦1,667 = $1
            "GHS": Decimal("0.00820"),   # Updated realistic rate
            "KES": Decimal("0.07800"),
        }
        rate = fallback_rates.get(to_currency, Decimal("1.00"))
        print(f"[CurrencyService] Fallback rate: 1 NGN = {rate} {to_currency}")
        return rate

    @staticmethod
    def convert_to_currency(amount_ngn: Decimal, target_currency: str) -> Decimal:
        """Convert NGN amount to target currency (Correct formula: multiply by rate)."""
        target_currency = target_currency.upper()
        
        print(f"\n[CurrencyService] Converting {amount_ngn} NGN → {target_currency}")

        rate = CurrencyService.get_exchange_rate("NGN", target_currency)
        
        # FIXED: Use multiplication instead of division
        converted = amount_ngn * rate

        final_amount = converted.quantize(Decimal("0.01"))

        print(f"[CurrencyService] Rate used: 1 NGN = {rate} {target_currency}")
        print(f"[CurrencyService] Result: {amount_ngn} NGN = {final_amount} {target_currency}\n")

        return final_amount