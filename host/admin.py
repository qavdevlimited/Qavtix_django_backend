from django.contrib import admin

from host.models import Host,HostSubscription,HostNotification,EmailCampaign,CampaignUsage,CheckIn,HostLink

# Register your models here.


admin.site.register(Host)
admin.site.register(HostSubscription)
admin.site.register(HostNotification)
admin.site.register(EmailCampaign)
admin.site.register(CampaignUsage)
admin.site.register(CheckIn)
admin.site.register(HostLink)