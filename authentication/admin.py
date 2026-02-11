from django.contrib import admin
from .models import PasswordResetOTP, PasswordResetToken
# Register your models here.
admin.site.register(PasswordResetOTP)
admin.site.register(PasswordResetToken)