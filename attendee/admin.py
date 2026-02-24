from django.contrib import admin

from attendee.models import Attendee,FavoriteEvent,AffliateEarnings,AffiliateLink,PayoutInformation

# Register your models here.
admin.site.register(Attendee)
admin.site.register(FavoriteEvent)
admin.site.register(AffliateEarnings)
admin.site.register(AffiliateLink)
admin.site.register(PayoutInformation)