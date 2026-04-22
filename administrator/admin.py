from django.contrib import admin

from administrator.models import Admin, AdminOTP,SystemConfig,AutoPayout

# Register your models here.
admin.site.register(Admin)
admin.site.register(AdminOTP)
admin.site.register(SystemConfig)
admin.site.register(AutoPayout)
