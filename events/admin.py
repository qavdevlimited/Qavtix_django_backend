from django.contrib import admin
from .models import Tag,Event,EventMedia,EventLocation,EventPermission,Ticket
# Register your models here.


admin.site.register(Tag)
admin.site.register(Event)
admin.site.register(EventLocation)
admin.site.register(EventMedia)
admin.site.register(EventPermission)
admin.site.register(Ticket)