

from .paystack_service import PaystackGateway

# Map country codes → gateway
# Add more gateways here as you integrate them
_GATEWAY_MAP = {
    "NG": PaystackGateway,
    # "US": StripeGateway,
    # "GB": StripeGateway,
}

_DEFAULT_GATEWAY = PaystackGateway


def get_gateway(country: str):
    """
    Returns the appropriate gateway instance for a country code.
    Falls back to Paystack if country not mapped.
    """
    cls = _GATEWAY_MAP.get(country.upper(), _DEFAULT_GATEWAY)
    return cls()