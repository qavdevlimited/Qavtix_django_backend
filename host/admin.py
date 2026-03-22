from django.contrib import admin

from host.models import Host,HostSubscription,HostNotification

# Register your models here.


admin.site.register(Host)
admin.site.register(HostSubscription)
admin.site.register(HostNotification)