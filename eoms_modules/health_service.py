from datetime import datetime


class HealthService:
    """
    Standard health report builder for EOMS services.
    """

    @staticmethod
    def now():
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def result(component, status="Unknown", message="", details=None, errors=None, warnings=None):
        return {
            "component": component,
            "status": status,
            "last_check": HealthService.now(),
            "message": message,
            "details": details or {},
            "errors": errors or [],
            "warnings": warnings or [],
        }

    @staticmethod
    def healthy(component, message="", details=None):
        return HealthService.result(
            component=component,
            status="Healthy",
            message=message,
            details=details,
        )

    @staticmethod
    def warning(component, message="", details=None, warnings=None):
        return HealthService.result(
            component=component,
            status="Warning",
            message=message,
            details=details,
            warnings=warnings or [],
        )

    @staticmethod
    def failed(component, message="", details=None, errors=None):
        return HealthService.result(
            component=component,
            status="Failed",
            message=message,
            details=details,
            errors=errors or [],
        )