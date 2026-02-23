from django.contrib import admin

from attendee.models import Attendee,FavoriteEvent

# Register your models here.
admin.site.register(Attendee)
admin.site.register(FavoriteEvent)