from django.contrib import admin
from .models import Payment, AttendeePlan,PayoutInformation

admin.site.register(AttendeePlan)
admin.site.register(Payment)
admin.site.register(PayoutInformation)