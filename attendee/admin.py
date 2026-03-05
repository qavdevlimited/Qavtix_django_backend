from django.contrib import admin

from attendee.models import Attendee,FavoriteEvent,AffliateEarnings,AffiliateLink,TwoFactorAuths,TicketGroup,GroupMember,AccountDeletionRequest

# Register your models here.
admin.site.register(Attendee)
admin.site.register(FavoriteEvent)
admin.site.register(AffliateEarnings)
admin.site.register(AffiliateLink)
admin.site.register(TwoFactorAuths)
admin.site.register(TicketGroup)
admin.site.register(GroupMember)
admin.site.register(AccountDeletionRequest)



