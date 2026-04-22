class AdminScope:
    def __init__(self, admin):
        self.is_super = admin.role == "super_admin"
        self.country = admin.country_assignment




class ScopedQuery:

    @staticmethod
    def apply_country(qs, scope, field_path):
        if scope.is_super:
            return qs

        return qs.filter(
            **{f"{field_path}__iexact": scope.country}
        )