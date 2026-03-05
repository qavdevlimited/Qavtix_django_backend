from django.contrib import admin
from .models import Payment,PaymentCard,PayoutInformation
# Register your models here.
admin.site.register(Payment)
admin.site.register(PaymentCard)
admin.site.register(PayoutInformation)