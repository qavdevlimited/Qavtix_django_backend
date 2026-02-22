from .stripe_service import StripeGateway
from .paystack_service import PaystackGateway

def get_gateway(country_code):
    if country_code in ["NG", "GH"]:
        return PaystackGateway()
    return StripeGateway()