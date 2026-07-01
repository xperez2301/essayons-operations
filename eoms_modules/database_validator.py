from __future__ import annotations

from typing import Any


def is_missing(value: Any) -> bool:
    return value is None or str(value).strip() == ""


class DatabaseValidator:
    """
    Validates EOMS records and reports possible database issues.

    This class stays independent from Flask.
    Routes should call DatabaseCenterService, not this class directly.
    """

    def validate_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        report = {
            "status": "ok",
            "total_records": len(records),
            "missing_address": [],
            "missing_city": [],
            "missing_zip": [],
            "bad_coordinates": [],
            "duplicate_bols": [],
            "needs_legacy_repair": [],
        }

        seen_bols = {}

        for record in records:
            bol = str(record.get("bol") or record.get("bol_number") or "").strip()

            if is_missing(record.get("address")):
                report["missing_address"].append(record)

            if is_missing(record.get("city")):
                report["missing_city"].append(record)

            if is_missing(record.get("zip")) and is_missing(record.get("zipcode")):
                report["missing_zip"].append(record)

            lat = record.get("lat") or record.get("latitude")
            lng = record.get("lng") or record.get("lon") or record.get("longitude")

            try:
                lat_float = float(lat)
                lng_float = float(lng)
                if not (-90 <= lat_float <= 90) or not (-180 <= lng_float <= 180):
                    report["bad_coordinates"].append(record)
            except (TypeError, ValueError):
                report["bad_coordinates"].append(record)

            if bol:
                if bol in seen_bols:
                    report["duplicate_bols"].append(record)
                else:
                    seen_bols[bol] = True

            store_name = record.get("store_name") or ""
            if "Addr ess:" in store_name or "City/S tate/Zip:" in store_name:
                report["needs_legacy_repair"].append(record)

        report["issue_count"] = (
            len(report["missing_address"])
            + len(report["missing_city"])
            + len(report["missing_zip"])
            + len(report["bad_coordinates"])
            + len(report["duplicate_bols"])
            + len(report["needs_legacy_repair"])
        )

        return report


def validate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Backward-compatible wrapper for old code that still imports validate_records().
    """
    return DatabaseValidator().validate_records(records)