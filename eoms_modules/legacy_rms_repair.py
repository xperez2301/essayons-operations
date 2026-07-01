from __future__ import annotations

import re
from typing import Any


class LegacyRMSRepair:
    """
    Repairs malformed RMS records where address, city, state, ZIP,
    and contact data were incorrectly stored inside store_name.

    This class is independent from Flask.
    """

    def needs_repair(self, record: dict[str, Any]) -> bool:
        store_name = record.get("store_name") or ""
        address = record.get("address") or ""
        city = record.get("city") or ""

        return (
            ("Addr ess:" in store_name or "City/S tate/Zip:" in store_name)
            and (not address or not city)
        )

    def parse_store_blob(self, value: str) -> dict[str, str]:
        text = value or ""

        repaired = {
            "store_name": "",
            "address": "",
            "city": "",
            "state": "",
            "zip": "",
            "contact": "",
        }

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        if lines:
            repaired["store_name"] = lines[0]

        address_match = re.search(
            r"Addr\s*ess:\s*(.+?)(?=City\/S\s*tate\/Zip:|Contact:|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )

        city_match = re.search(
            r"City\/S\s*tate\/Zip:\s*([^,\n]+),?\s*([A-Za-z]{2,}|Texas|TX)?\s*(\d{5})?",
            text,
            re.IGNORECASE,
        )

        contact_match = re.search(
            r"Contact:\s*(.+)",
            text,
            re.IGNORECASE,
        )

        if address_match:
            repaired["address"] = " ".join(address_match.group(1).split())

        if city_match:
            repaired["city"] = (city_match.group(1) or "").strip()
            state = (city_match.group(2) or "").strip()
            repaired["state"] = "TX" if state.lower() == "texas" else state.upper()
            repaired["zip"] = (city_match.group(3) or "").strip()

        if contact_match:
            repaired["contact"] = contact_match.group(1).strip()

        return repaired

    def repair_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if not self.needs_repair(record):
            return record

        repaired_fields = self.parse_store_blob(record.get("store_name") or "")

        repaired_record = dict(record)
        repaired_record.update(
            {
                key: value
                for key, value in repaired_fields.items()
                if value
            }
        )

        repaired_record["legacy_rms_repaired"] = True

        return repaired_record


def parse_legacy_store_blob(value: str) -> dict[str, str]:
    """
    Backward-compatible wrapper for old imports.
    """
    return LegacyRMSRepair().parse_store_blob(value)


def needs_legacy_rms_repair(record: dict[str, Any]) -> bool:
    """
    Backward-compatible wrapper for old imports.
    """
    return LegacyRMSRepair().needs_repair(record)