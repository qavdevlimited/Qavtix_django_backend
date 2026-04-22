from rest_framework.exceptions import PermissionDenied

class SuperAdminRequiredMixin:
    """
    Mixin to restrict access to superadmins only.
    """

    def initial(self, request, *args, **kwargs):
        # Run DRF's normal initialization first
        super().initial(request, *args, **kwargs)

        user = request.user

        if not user or not user.is_authenticated:
            raise PermissionDenied("Authentication required.")

        if not user.is_superuser:
            raise PermissionDenied("You do not have permission to access this resource.")
        



class SuperAdminWriteMixin:
    """
    Allows read (GET) for all authenticated admins,
    but restricts write actions (PATCH, DELETE, POST) to superadmins only.
    """

    def check_permissions(self, request):
        super().check_permissions(request)

        if request.method in ["PATCH", "POST", "PUT", "DELETE"]:
            if not request.user.is_superuser:
                raise PermissionDenied("Only superadmins can modify this resource.")