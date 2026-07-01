import os
from typing import Any


class AzureHealthService:
    """
    Reports Azure-related health for EOMS.
    """

    def __init__(self, app=None):
        self.app = app

    def status(self) -> dict[str, Any]:
        is_azure = bool(
            os.environ.get("WEBSITE_SITE_NAME")
            or os.environ.get("WEBSITE_INSTANCE_ID")
        )

        azure_maps_key = ""
        if self.app:
            azure_maps_key = (
                os.environ.get("AZURE_MAPS_KEY")
                or str(self.app.config.get("AZURE_MAPS_KEY", ""))
            )

        checks = {
            "running_in_azure": is_azure,
            "azure_maps_key_configured": bool(azure_maps_key),
            "website_site_name": os.environ.get("WEBSITE_SITE_NAME", ""),
        }

        if not azure_maps_key:
            return {
                "name": "Azure",
                "status": "warning",
                "message": "Azure Maps key is not configured.",
                "details": checks,
            }

        return {
            "name": "Azure",
            "status": "ok",
            "message": "Azure configuration looks ready.",
            "details": checks,
        }