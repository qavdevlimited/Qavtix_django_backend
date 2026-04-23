from decimal import Decimal
from payments.services.currency_service import CurrencyService

def pagination_data(paginator):
    page = paginator.page
    return {
        "count":       page.paginator.count,
        "total_pages": page.paginator.num_pages,
        "page":        page.number,
        "next":        page.next_page_number()     if page.has_next()     else None,
        "previous":    page.previous_page_number() if page.has_previous() else None,
    }





def convert_to_ngn(amount, currency):
    from payments.services.currency_service import CurrencyService

    if currency == "NGN":
        return amount

    rate = CurrencyService.get_exchange_rate("NGN", currency)
    return (amount / rate).quantize(Decimal("0.01"))



def get_admin_currency(user):
    """
    Returns the admin's currency based on their assigned country.
    """
    from payments.services.currency_utils import get_currency_for_country

    if not user or not hasattr(user, "admin_profile"):
        return "NGN"  # safe fallback

    country = user.admin_profile.country_assignment
    return get_currency_for_country(country)