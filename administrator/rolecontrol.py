"""
administrator/service/role_control.py

Role-based access control for admin views and services.
Restricts data visibility based on:
1. Admin type: superadmin (sees all) vs normal admin (restricted by country)
2. Country assignment: normal admins only see data from their assigned country

This is the SOURCE OF TRUTH for access control.
All services should call these methods to filter querysets.

USAGE IN SERVICES:
    from administrator.service.role_control import RoleControlService
    
    def get_customers(country=None, ...):
        qs = Attendee.objects.all()
        qs = RoleControlService.filter_by_admin(admin_user, qs, "attendee")
        # ... rest of filtering
        return qs
"""

import logging
from django.core.exceptions import PermissionDenied
from django.db.models import Q

logger = logging.getLogger(__name__)


class RoleControlService:
    """
    Service for applying role-based access control to querysets.
    Central point for all admin data visibility rules.
    """

    @staticmethod
    def is_superadmin(user):
        """Check if user is a superadmin (sees all data)."""
        return user.is_superuser

    @staticmethod
    def get_admin_country(user):
        """
        Get the country assigned to an admin.
        Raises PermissionDenied if not an admin.
        Returns None for superadmins (they see all).
        """
        from administrator.models import Admin

        if RoleControlService.is_superadmin(user):
            return None  # Superadmins see all countries

        try:
            admin = Admin.objects.select_related().get(user=user)
        except Admin.DoesNotExist:
            raise PermissionDenied("User is not an admin.")

        if not admin.country_assignment:
            raise PermissionDenied(
                "Admin has no assigned country. Contact system administrator."
            )

        return admin.country_assignment

    @staticmethod
    def get_country_field_for_model(model_name):
        """
        Map model names to their country field paths.
        Used to determine which field to filter on.
        """
        field_map = {
            # Direct country field
            "host": "country",
            "attendee": "country",

            # Through relationships
            "event": "host__country",
            "order": "event__host__country",
            "flaggeduser": "user__host_profile__country",
            "issuedticket": "event__host__country",
            "orderticket": "order__event__host__country",
            "featuredplanevent": "event__host__country",
            "hoststrictsubscription": "host__country",
            "affliateearnings": "attendee__country",
            "marketlisting": "seller__attendee_profile__country",
            "featuredevent": "user__host_profile__country",
            "hoststrictsubscription": "host__country",
        }

        return field_map.get(model_name.lower(), None)

    MULTI_PATH_MODELS = {
        "withdrawal": Q(user__host_profile__country="{country}") | Q(user__attendee_profile__country="{country}"),
    }

    @staticmethod
    def filter_by_admin(user, queryset, model_name):
        
        if not user.is_authenticated:
            return queryset.none()

        # Superadmins see everything
        if RoleControlService.is_superadmin(user):
            logger.debug(f"Superadmin {user.email} accessing {model_name} — no country filter applied")
            return queryset

        # Normal admin — filter by country
        admin_country = RoleControlService.get_admin_country(user)

        if model_name.lower() in RoleControlService.MULTI_PATH_MODELS:
            q_template = RoleControlService.MULTI_PATH_MODELS[model_name.lower()]
            # Rebuild the Q with the actual country value
            q_filter = (
                Q(user__host_profile__country=admin_country) |
                Q(user__attendee_profile__country=admin_country)
            )
            logger.debug(f"Multi-path filter applied for {model_name} — country: {admin_country}")
            return queryset.filter(q_filter)
    
        country_field = RoleControlService.get_country_field_for_model(model_name)

        if not country_field:
            logger.warning(
                f"No country field mapping for model {model_name}. "
                f"Returning filtered queryset with no results as safety measure."
            )
            return queryset.none()

        filter_kwargs = {country_field: admin_country}
        filtered = queryset.filter(**filter_kwargs)

        logger.debug(
            f"Normal admin {user.email} accessing {model_name} — "
            f"filtered to country: {admin_country}"
        )
        return filtered

    @staticmethod
    def verify_object_access(user, obj, model_name):
        """
        Verify a specific object is accessible to the admin user.
        Used in detail views to prevent accessing out-of-scope objects.

        Args:
            user: The admin user
            obj: The model instance to verify access to
            model_name: The name of the model

        Raises:
            PermissionDenied: If user cannot access this object

        Returns:
            True if access is allowed
        """
        if not user.is_authenticated:
            raise PermissionDenied("User is not authenticated.")

        # Superadmins can access anything
        if RoleControlService.is_superadmin(user):
            return True

        # Normal admin — verify country
        admin_country = RoleControlService.get_admin_country(user)
        country_field = RoleControlService.get_country_field_for_model(model_name)

        if not country_field:
            raise PermissionDenied(f"Cannot determine access rules for {model_name}.")

        # Navigate nested field (e.g., "event__host__country")
        parts = country_field.split("__")
        obj_country = obj
        for part in parts:
            obj_country = getattr(obj_country, part, None)
            if obj_country is None:
                raise PermissionDenied(f"Cannot determine country for {model_name}.")

        if obj_country != admin_country:
            raise PermissionDenied(
                f"Object is outside your assigned country scope ({admin_country})."
            )

        return True

    @staticmethod
    def filter_multiple_models(user, filters_dict):
        """
        Apply filtering to multiple querysets at once.
        Useful for complex dashboards or reports.

        Args:
            user: The admin user
            filters_dict: Dict of {model_name: queryset}

        Returns:
            Dict of {model_name: filtered_queryset}

        Example:
            results = RoleControlService.filter_multiple_models(user, {
                "host": Host.objects.all(),
                "event": Event.objects.all(),
                "order": Order.objects.all(),
            })
            hosts = results["host"]
            events = results["event"]
        """
        filtered = {}
        for model_name, qs in filters_dict.items():
            filtered[model_name] = RoleControlService.filter_by_admin(user, qs, model_name)
        return filtered

    @staticmethod
    def get_access_info(user):
        """
        Get human-readable access info for an admin.
        Useful for logging and debugging.

        Returns:
            Dict with access_type, country_assignment (if applicable)
        """
        if not user.is_authenticated:
            return {"access_type": "none", "country": None}

        if RoleControlService.is_superadmin(user):
            return {"access_type": "superadmin", "country": "all"}

        try:
            admin_country = RoleControlService.get_admin_country(user)
            return {"access_type": "normal_admin", "country": admin_country}
        except PermissionDenied:
            return {"access_type": "admin_no_country", "country": None}