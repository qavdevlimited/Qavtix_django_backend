from django.urls import path


from administrator.views import AdminLoginView, AdminOTPVerifyView


urlpatterns = [
path("admin/login/",        AdminLoginView.as_view(),     name="admin-login"),
path("admin/login/verify/", AdminOTPVerifyView.as_view(), name="admin-otp-verify"),

]