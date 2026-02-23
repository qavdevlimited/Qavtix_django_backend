# create_issued_tickets.py

import os
import django
import uuid
from django.utils import timezone

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Qavtix.settings")
django.setup()

# Import your models
from transactions.models import Order
from transactions.models import IssuedTicket


def generate_ticket_code():
    return f"TKT-{uuid.uuid4().hex[:10].upper()}"


def create_issued_tickets():
    """Create issued tickets for all completed orders that don't have tickets yet."""
    orders = Order.objects.filter(status="completed").exclude(issuedticket__isnull=False)

    for order in orders:
        print(f"Processing order {order.id}...")
        tickets_created = 0

        for order_ticket in order.tickets.all():
            for _ in range(order_ticket.quantity):
                IssuedTicket.objects.create(
                    order=order,
                    order_ticket=order_ticket,
                    event=order.event,
                    owner=order.user,
                    original_owner=order.user,
                    status="active",
                    metadata={},
                )
                tickets_created += 1

        # Update order metadata
        order.metadata = order.metadata or {}
        order.metadata["issued_tickets_created_at"] = timezone.now().isoformat()
        order.save(update_fields=["metadata"])

        print(f"Created {tickets_created} tickets for order {order.id}")

    print("All eligible tickets created ✅")


if __name__ == "__main__":
    create_issued_tickets()