from django.contrib import admin
from .models import Order,Ticket,IssuedTicket,TicketTransferHistory,Withdrawal,SplitParticipant,SplitOrder,FeaturedEvent,OrderTicket
# Register your models here.



admin.site.register(Order)
admin.site.register(IssuedTicket)
admin.site.register(TicketTransferHistory)
admin.site.register(Withdrawal)
admin.site.register(SplitParticipant)
admin.site.register(SplitOrder)
admin.site.register(FeaturedEvent)
admin.site.register(OrderTicket)