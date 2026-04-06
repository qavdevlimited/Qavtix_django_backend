from django.contrib import admin

from administrator.models import Admin, AdminOTP,SystemConfig,SystemConfigSeed

# Register your models here.
admin.site.register(Admin)
admin.site.register(AdminOTP)
admin.site.register(SystemConfig)
