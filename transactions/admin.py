from django.contrib import admin
from .models import Order,Ticket,IssuedTicket,TicketTransferHistory,Withdrawal
# Register your models here.



admin.site.register(Order)
admin.site.register(IssuedTicket)
admin.site.register(TicketTransferHistory)
admin.site.register(Withdrawal)
