# payments/currency_utils.py

COUNTRY_CURRENCY_MAP = {
    "nigeria":      "NGN",
    "ghana":        "GHS",
    "kenya":        "KES",
    "south africa": "ZAR",
}

DEFAULT_CURRENCY = "USD"


def get_currency_for_country(country: str) -> str:
    """
    Returns the Paystack currency code for a given country name.
    Case-insensitive. Falls back to USD for unsupported countries.
    """
    if not country:
        return DEFAULT_CURRENCY
    return COUNTRY_CURRENCY_MAP.get(country.lower().strip(), DEFAULT_CURRENCY)


def get_currency_for_host(host) -> str:
    """
    Returns the currency for a host based on their country.
    """
    country = getattr(host, "country", "") or ""
    return get_currency_for_country(country)


def get_currency_for_event(event) -> str:
    """
    Returns the currency for an event based on its host's country.
    This is the single source of truth for all payment flows.
    """
    host    = getattr(event, "host", None)
    country = getattr(host, "country", "") or "" if host else ""
    return get_currency_for_country(country)


def get_gateway_country_code(currency: str) -> str:
    """
    Maps currency back to a country code for get_gateway() routing.
    All four currencies use Paystack so all return "NG" for now.
    When you add other gateways, update this mapping.
    """
    return "NG"  # All supported currencies use Paystack