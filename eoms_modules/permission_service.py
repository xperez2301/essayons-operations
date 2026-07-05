def clean(value):
    return str(value or "").strip()


ROLE_ADMIN = "admin"
ROLE_DISPATCHER = "dispatcher"
ROLE_DRIVER = "driver"


class PermissionService:
    def role(self, user):
        if not user:
            return ""
        return clean(user.get("role")).lower()

    def is_admin(self, user):
        return self.role(user) == ROLE_ADMIN

    def is_dispatcher(self, user):
        return self.role(user) == ROLE_DISPATCHER

    def is_driver(self, user):
        return self.role(user) == ROLE_DRIVER

    def can_view_financials(self, user):
        return self.is_admin(user)

    def can_view_profit(self, user):
        return self.is_admin(user)

    def can_view_payroll(self, user):
        return self.is_admin(user)

    def can_import_rms(self, user):
        return self.is_admin(user)

    def can_manage_users(self, user):
        return self.is_admin(user)

    def can_dispatch(self, user):
        return self.is_admin(user) or self.is_dispatcher(user)

    def can_use_route_builder(self, user):
        return self.is_admin(user) or self.is_dispatcher(user)

    def can_view_driver_portal(self, user):
        return self.is_driver(user)

    def can_view_gps(self, user):
        return self.is_admin(user)

    def dashboard_profile(self, user):
        if self.is_admin(user):
            return "admin"
        if self.is_dispatcher(user):
            return "dispatcher"
        if self.is_driver(user):
            return "driver"
        return "guest"


permissions = PermissionService()