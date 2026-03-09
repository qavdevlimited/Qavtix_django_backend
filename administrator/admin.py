from django.contrib import admin

from administrator.models import Admin, AdminOTP

# Register your models here.
admin.site.register(Admin)
admin.site.register(AdminOTP)