from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime

from eoms_modules.duplicate_bol_cleanup_service import normalize_bol_number


TEST_DEMO_PATTERN = re.compile(r"\b(test|demo|sample|mock|fake|training)\b", re.IGNORECASE)
ACTIVE_STATUSES = {"unassigned", "assigned", "in transit", "need review", "ready", "open", "pending"}
COMPLETED_STATUSES = {"completed", "complete", "closed"}
RECOVERED_STATUSES = {"recovered", "recovery complete"}
RECEIVED_STATUSES = {"received", "verified", "warehouse received", "received complete"}
ARCHIVED_STATUSES = {"archived", "inactive", "cancelled", "canceled", "deleted", "void"}


def clean(value):
    return "" if value is None else str(value).strip()


def parse_datetime(value):
    value = clean(value)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def normalized_status_category(record):
    raw_status = clean(record.get("status")).lower()
    rms_status = clean(record.get("rms_status")).lower()
    receiving_status = clean(record.get("receiving_status")).lower()
    recovery_status = clean(record.get("recovery_status")).lower()

    if raw_status in ARCHIVED_STATUSES:
        return "Archived/Inactive"
    if raw_status in RECOVERED_STATUSES or recovery_status in RECOVERED_STATUSES or clean(record.get("recovered_at")):
        return "Recovered"
    if raw_status in RECEIVED_STATUSES or receiving_status in RECEIVED_STATUSES or clean(record.get("received_at")):
        return "Received"
    if raw_status in COMPLETED_STATUSES or clean(record.get("completed_at")) or clean(record.get("closed_at")):
        return "Completed"
    if raw_status in ACTIVE_STATUSES or rms_status == "open in rms":
        return "Active"
    if not raw_status:
        return "Missing Status"
    return "Uncertain"


def has_route_reference(record, routes=None):
    routes = routes or []
    record_id = clean(record.get("id"))
    if clean(record.get("route_id")) or clean(record.get("route")) or clean(record.get("route_name")):
        return True
    for route in routes:
        if record_id and record_id in (route.get("store_ids") or []):
            return True
        for stop in route.get("stops") or []:
            if isinstance(stop, dict) and clean(stop.get("id")) == record_id:
                return True
    return False


def route_name(record, routes=None):
    route_id = clean(record.get("route_id") or record.get("route"))
    explicit = clean(record.get("route_name") or record.get("route_label"))
    if explicit:
        return explicit
    for route in routes or []:
        if route_id and route_id == clean(route.get("id") or route.get("route_id")):
            return clean(route.get("name") or route.get("route_name") or route.get("driver") or route_id)
    return ""


def source_identifier(record):
    return clean(
        record.get("rms_id")
        or record.get("rms_bol_id")
        or record.get("source_id")
        or record.get("source_identifier")
        or record.get("rms_url")
        or record.get("source_file")
        or record.get("pdf_path")
    )


def is_test_demo_record(record):
    text = json.dumps(record, default=str)
    return bool(TEST_DEMO_PATTERN.search(text))


def latest_operational_timestamp(record):
    for field in ("updated_at", "completed_at", "closed_at", "recovered_at", "received_at", "last_seen_in_rms_at"):
        if clean(record.get(field)):
            return clean(record.get(field))
    return ""


def record_age_days(record, now=None):
    now = now or datetime.now()
    created = parse_datetime(record.get("created_at"))
    if not created:
        return None
    if created.tzinfo and not now.tzinfo:
        now = now.replace(tzinfo=created.tzinfo)
    return max(0, (now - created).days)


def age_bucket(age_days):
    if age_days is None:
        return "Missing"
    if age_days > 180:
        return ">180 days"
    if age_days > 90:
        return ">90 days"
    if age_days > 60:
        return ">60 days"
    if age_days > 30:
        return ">30 days"
    return "0-30 days"


def missing_field_flags(record, has_route):
    flags = []
    normalized_bol = normalize_bol_number(record.get("bol"))
    rms_status = clean(record.get("rms_status")).lower()
    if not normalized_bol or not any(ch.isdigit() for ch in normalized_bol) or len(normalized_bol) < 3:
        flags.append("missing_or_invalid_bol")
    if not clean(record.get("status")):
        flags.append("missing_status")
    if not clean(record.get("created_at")):
        flags.append("missing_created_timestamp")
    if not latest_operational_timestamp(record):
        flags.append("missing_updated_timestamp")
    if not has_route:
        flags.append("no_route_reference")
    if not source_identifier(record):
        flags.append("no_source_identifier")
    if is_test_demo_record(record):
        flags.append("test_demo_sample")
    if rms_status == "missing from rms":
        flags.append("missing_from_rms")
    if rms_status in {"closed in rms", "closed by rms"}:
        flags.append("closed_in_rms")
    if rms_status == "open in rms":
        flags.append("open_in_rms")
    return flags


def record_reason(category, flags, age_days):
    if category == "Active":
        return "Active because the stored status is operational or RMS still reports it open."
    if category in {"Completed", "Recovered", "Received", "Archived/Inactive"}:
        return f"Historical because it is classified as {category.lower()}."
    if category == "Missing Status":
        return "Incomplete because the stored status is missing."
    if "missing_or_invalid_bol" in flags:
        return "Incomplete because the BOL number is missing or invalid."
    if "test_demo_sample" in flags:
        return "Suspicious because test/demo/sample wording was detected."
    if age_days is not None and age_days > 90:
        return "Suspicious because the record is older than 90 days and is not clearly historical."
    return "Uncertain because the status is unfamiliar and no safe assumption was made."


def audit_record(record, routes=None, now=None):
    normalized_bol = normalize_bol_number(record.get("bol"))
    category = normalized_status_category(record)
    has_route = has_route_reference(record, routes)
    age_days = record_age_days(record, now)
    flags = missing_field_flags(record, has_route)
    if category == "Uncertain":
        flags.append("uncertain_status")
    return {
        "record_id": clean(record.get("id")),
        "raw_bol": clean(record.get("bol")),
        "normalized_bol": normalized_bol,
        "store_origin": clean(record.get("store_name") or record.get("origin_name") or record.get("origin")),
        "raw_status": clean(record.get("status")),
        "normalized_status_category": category,
        "hub": clean(record.get("hub")),
        "route_id": clean(record.get("route_id") or record.get("route")),
        "route_name": route_name(record, routes),
        "has_route_reference": has_route,
        "created_at": clean(record.get("created_at")),
        "latest_operational_timestamp": latest_operational_timestamp(record),
        "source_identifier": source_identifier(record),
        "rms_status": clean(record.get("rms_status")),
        "age_days": age_days,
        "age_bucket": age_bucket(age_days),
        "audit_flags": flags,
        "active_or_historical": "Historical" if category in {"Completed", "Recovered", "Received", "Archived/Inactive"} else "Active" if category == "Active" else "Uncertain",
        "reason": record_reason(category, flags, age_days),
    }


def bol_data_audit_report(stores, routes=None, now=None):
    routes = routes or []
    now = now or datetime.now()
    rows = [audit_record(record, routes, now) for record in stores or []]

    normalized_keys = [row["normalized_bol"] for row in rows if row["normalized_bol"]]
    duplicate_groups = sum(1 for _, count in Counter(normalized_keys).items() if count > 1)
    category_counts = Counter(row["normalized_status_category"] for row in rows)
    status_breakdown_counter = Counter((row["raw_status"] or "(missing)", row["normalized_status_category"]) for row in rows)
    flag_counts = Counter(flag for row in rows for flag in row["audit_flags"])

    metrics = {
        "total_bol_records": len(rows),
        "unique_normalized_bols": len(set(normalized_keys)),
        "duplicate_groups": duplicate_groups,
        "active_records": category_counts["Active"],
        "completed_records": category_counts["Completed"],
        "recovered_records": category_counts["Recovered"],
        "received_records": category_counts["Received"],
        "archived_inactive_records": category_counts["Archived/Inactive"],
        "uncertain_records": category_counts["Uncertain"],
        "missing_status_records": category_counts["Missing Status"],
        "older_than_30_days": sum(1 for row in rows if row["age_days"] is not None and row["age_days"] > 30),
        "older_than_60_days": sum(1 for row in rows if row["age_days"] is not None and row["age_days"] > 60),
        "older_than_90_days": sum(1 for row in rows if row["age_days"] is not None and row["age_days"] > 90),
        "older_than_180_days": sum(1 for row in rows if row["age_days"] is not None and row["age_days"] > 180),
        "records_with_no_route_reference": flag_counts["no_route_reference"],
        "records_with_no_rms_source_identifier": flag_counts["no_source_identifier"],
        "test_demo_sample_records": flag_counts["test_demo_sample"],
        "missing_or_invalid_bol_records": flag_counts["missing_or_invalid_bol"],
        "missing_created_timestamp_records": flag_counts["missing_created_timestamp"],
        "missing_updated_timestamp_records": flag_counts["missing_updated_timestamp"],
        "open_in_rms_records": flag_counts["open_in_rms"],
        "missing_from_rms_records": flag_counts["missing_from_rms"],
        "closed_in_rms_records": flag_counts["closed_in_rms"],
    }

    status_breakdown = [
        {"raw_status": raw, "normalized_status_category": category, "record_count": count}
        for (raw, category), count in sorted(status_breakdown_counter.items(), key=lambda item: (item[0][1], item[0][0]))
    ]

    return {
        "ok": True,
        "scan_time": now.isoformat(timespec="seconds"),
        "metrics": metrics,
        "status_breakdown": status_breakdown,
        "records": rows,
        "filters": {
            "categories": sorted({row["normalized_status_category"] for row in rows}),
            "hubs": sorted({row["hub"] for row in rows if row["hub"]}),
            "age_buckets": ["0-30 days", ">30 days", ">60 days", ">90 days", ">180 days", "Missing"],
            "sources": sorted({row["source_identifier"] for row in rows if row["source_identifier"]})[:100],
            "flags": sorted(flag_counts.keys()),
        },
    }
