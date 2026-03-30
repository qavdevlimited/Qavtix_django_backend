from decimal import Decimal
from django.utils import timezone
from marketplace.models import MarketListing


class MarketplaceListingError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status  = status
        super().__init__(message)
 
 
def validate_listing_currency(issued_ticket, seller):
    """
    Blocks listing if the ticket was purchased in a currency that doesn't
    match the seller's host country currency.
 
    Rule: you can only resell tickets you bought in your own currency.
    A Nigerian buyer who bought a GHS ticket cannot list it for resale.
 
    Call this before creating a MarketListing.
    """
    from payments.services.currency_utils import get_currency_for_event, get_currency_for_host
 
    event           = issued_ticket.event
    ticket_currency = get_currency_for_event(event)
 
    # Check if seller has a host profile — attendees may not
    # Use attendee's country if available, otherwise skip check
    attendee = getattr(seller, "attendee_profile", None)
    if not attendee:
        return  # no profile to check against — allow listing
 
    seller_country   = getattr(attendee, "country", "") or ""
 
    from payments.services.currency_utils import get_currency_for_country
    seller_currency = get_currency_for_country(seller_country)
 
    if ticket_currency != seller_currency:
        raise MarketplaceListingError(
            f"This ticket was purchased in {ticket_currency} and cannot be resold "
            f"on the marketplace. You can only resell tickets purchased in your "
            f"local currency ({seller_currency}).",
            400,
        )
 


class MarketplaceListingService:

    @staticmethod
    def create_listing(user, ticket, price, expires_at=None):

       #check ownership
        if ticket.owner != user:
            raise MarketplaceListingError("You do not own this ticket.", 403)

        #check ticket status
        if ticket.status != "active":
            raise MarketplaceListingError("Only active tickets can be listed.", 400)

       
        validate_listing_currency(ticket, user)

       #check if already listed
        if hasattr(ticket, "market_listing") and ticket.market_listing.status == "active":
            raise MarketplaceListingError("This ticket is already listed.", 400)

       #check expiry
        if expires_at:
            if expires_at <= str(timezone.now()):
                raise MarketplaceListingError("Expiry must be in the future.", 400)

       #check price validity
        try:
            price = Decimal(price)
        except Exception:
            raise MarketplaceListingError("Invalid price value.", 400)

        if price <= 0:
            raise MarketplaceListingError("Price must be greater than zero.", 400)

       
        original_price = ticket.order_ticket.price  # or ticket.original_price if you have it

        max_allowed_price = original_price * Decimal("1.20")

        #check if price exceeds 20% above original price
        if price > max_allowed_price:
            raise MarketplaceListingError(
                f"Price cannot exceed 20% above original ticket price ({original_price}). "
                f"Max allowed is {max_allowed_price}.",
                400
            )

        # Event validity
        event = ticket.event

        if event.status != "active":
            raise MarketplaceListingError("Event is not active.", 400)

        if event.end_datetime <= timezone.now():
            raise MarketplaceListingError("Cannot list ticket for a past event.", 400)

        # Create listing
        listing = MarketListing.objects.create(
            ticket=ticket,
            seller=user,
            price=price,
            expires_at=expires_at
        )

        return listing
    

