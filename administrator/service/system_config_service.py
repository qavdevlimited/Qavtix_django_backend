# administrator/service/system_config_service.py

import logging
from django.db import transaction

logger = logging.getLogger(__name__)


class SystemConfigService:
    """
    All system config reads/writes go through here.
    Views never touch SystemConfig directly.
    """

    # ── Getters by section ────────────────────────────────────────────────────

    @staticmethod
    def get_general():
        from administrator.models import SystemConfig
        return {
            "platform_support_email": SystemConfig.get("platform_support_email", "inquiries@qavtix.com"),
            "default_currency":       SystemConfig.get("default_currency", {"code": "USD", "label": "US Dollar"}),
            "default_timezone":       SystemConfig.get("default_timezone", "Africa/Lagos"),
        }

    @staticmethod
    def get_policies():
        from administrator.models import SystemConfig
        return {
            "seller_verification_required": SystemConfig.get("seller_verification_required", True),
            "auto_approve_listing":         SystemConfig.get("auto_approve_listing", False),
        }

    @staticmethod
    def get_fees():
        from administrator.models import SystemConfig
        return {
            "ticket_resell_commission": SystemConfig.get("ticket_resell_commission", 25),
            "seller_service_fee":       SystemConfig.get("seller_service_fee", 10),
            "buyer_service_fee":        SystemConfig.get("buyer_service_fee", 10),
            "vat_enabled":              SystemConfig.get("vat_enabled", False),
            "prices_include_vat":       SystemConfig.get("prices_include_vat", False),
        }

    @staticmethod
    def get_fraud():
        from administrator.models import SystemConfig
        return {
            "fraud_sensitivity": SystemConfig.get("fraud_sensitivity", "medium"),
        }

    @staticmethod
    def get_notifications():
        from administrator.models import SystemConfig
        return {
            "email_notifications": SystemConfig.get("email_notifications", {}),
            "sms_notifications":   SystemConfig.get("sms_notifications", {}),
        }

    @staticmethod
    def get_localization():
        from administrator.models import SystemConfig
        return {
            "supported_countries":  SystemConfig.get("supported_countries", []),
            "supported_currencies": SystemConfig.get("supported_currencies", []),
            "language":             SystemConfig.get("language", "en"),
            "date_time_format":     SystemConfig.get("date_time_format", "24h"),
        }

    # ── Updaters by section ───────────────────────────────────────────────────

    @staticmethod
    @transaction.atomic
    def update_general(data, user=None):
        from administrator.models import SystemConfig
        updated = []
        allowed = ["platform_support_email", "default_currency", "default_timezone"]
        for key in allowed:
            if key in data:
                SystemConfig.set(key, data[key], user=user)
                updated.append(key)
        return updated

    @staticmethod
    @transaction.atomic
    def update_policies(data, user=None):
        from administrator.models import SystemConfig
        updated = []
        allowed = ["seller_verification_required", "auto_approve_listing"]
        for key in allowed:
            if key in data:
                SystemConfig.set(key, data[key], user=user)
                updated.append(key)
        return updated

    @staticmethod
    @transaction.atomic
    def update_fees(data, user=None):
        from administrator.models import SystemConfig
        updated = []
        allowed = [
            "ticket_resell_commission", "seller_service_fee",
            "buyer_service_fee", "vat_enabled", "prices_include_vat",
        ]
        for key in allowed:
            if key in data:
                SystemConfig.set(key, data[key], user=user)
                updated.append(key)
        return updated

    @staticmethod
    @transaction.atomic
    def update_fraud(data, user=None):
        from administrator.models import SystemConfig
        allowed_values = ["low", "medium", "high"]
        sensitivity = data.get("fraud_sensitivity")
        if sensitivity and sensitivity in allowed_values:
            SystemConfig.set("fraud_sensitivity", sensitivity, user=user)
            return ["fraud_sensitivity"]
        return []

    @staticmethod
    @transaction.atomic
    def update_notifications(data, user=None):
        from administrator.models import SystemConfig
        updated = []
        if "email_notifications" in data:
            SystemConfig.set("email_notifications", data["email_notifications"], user=user)
            updated.append("email_notifications")
        if "sms_notifications" in data:
            SystemConfig.set("sms_notifications", data["sms_notifications"], user=user)
            updated.append("sms_notifications")
        return updated

    @staticmethod
    @transaction.atomic
    def update_localization(data, user=None):
        from administrator.models import SystemConfig
        updated = []
        allowed = ["supported_countries", "supported_currencies", "language", "date_time_format"]
        for key in allowed:
            if key in data:
                SystemConfig.set(key, data[key], user=user)
                updated.append(key)
        return updated

    # ── Reset helpers ─────────────────────────────────────────────────────────

    SECTION_KEYS = {
        "general":       ["platform_support_email", "default_currency", "default_timezone"],
        "policies":      ["seller_verification_required", "auto_approve_listing"],
        "fees":          ["ticket_resell_commission", "seller_service_fee", "buyer_service_fee", "vat_enabled", "prices_include_vat"],
        "fraud":         ["fraud_sensitivity"],
        "notifications": ["email_notifications", "sms_notifications"],
        "localization":  ["supported_countries", "supported_currencies", "language", "date_time_format"],
    }

    @staticmethod
    def reset_to_last_saved(section):
        from administrator.models import SystemConfig
        keys = SystemConfigService.SECTION_KEYS.get(section, [])
        return SystemConfig.reset_to_last_saved(keys)

    @staticmethod
    def reset_all_to_defaults():
        from administrator.models import SystemConfig
        return SystemConfig.reset_to_default()