from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class SystemHealthService:
    """
    Aggregates EOMS system health into one operational status object.
    """

    def __init__(
        self,
        database_center_service=None,
        azure_health_service=None,
    ):
        self.database_center_service = database_center_service
        self.azure_health_service = azure_health_service

    def status(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "System Health Service",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "systems": {
                "database": self._database_status(),
                "rms": self._placeholder_status("RMS", "pending"),
                "azure": (
                    self.azure_health_service.status()
                    if self.azure_health_service
                    else self._placeholder_status("Azure", "pending")
                ),
                "github": self._placeholder_status("GitHub", "pending"),
                "auto_grab": self._placeholder_status("Auto Grab", "pending"),
                "gps7000_pro": self._placeholder_status("GPS7000 Pro", "pending"),
            },
        }

    def _database_status(self) -> dict[str, Any]:
        if self.database_center_service is None:
            return {
                "name": "Database",
                "status": "warning",
                "message": "DatabaseCenterService is not configured.",
            }

        service_status = self.database_center_service.status()

        return {
            "name": "Database",
            "status": "ok" if service_status.get("ok") else "warning",
            "message": "Database Center service is online.",
            "details": service_status,
        }

    def _placeholder_status(self, name: str, status: str = "pending") -> dict[str, Any]:
        return {
            "name": name,
            "status": status,
            "message": f"{name} health check is not wired yet.",
        }