from .stripe_service import StripeGateway


def get_gateway(country_code):
    if country_code in ["NG", "GH"]:
        pass
    return StripeGateway()