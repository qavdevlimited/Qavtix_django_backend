from django.contrib import admin
from .models import Tag,Event,EventMedia,EventLocation
# Register your models here.


admin.site.register(Tag)
admin.site.register(Event)
admin.site.register(EventLocation)
admin.site.register(EventMedia)