from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4


def clean(value):
    return "" if value is None else str(value).strip()


def normalize_bol_number(value):
    raw = clean(value).upper()
    if raw.startswith("BOL"):
        raw = raw[3:]
    return re.sub(r"[^A-Z0-9]", "", raw)


def parse_time(value):
    value = clean(value)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


OPERATIONAL_TIMESTAMP_FIELDS = (
    "assigned_at", "dispatched_at", "completed_at", "closed_at", "updated_at",
    "created_at", "recovered_at", "received_at", "dispatcher_closed_at",
    "inventory_updated_at", "fulfilled_at", "shipped_at",
)
NOTE_FIELDS = (
    "notes", "driver_exception_notes", "damage_notes", "warehouse_notes",
    "dispatcher_closeout_notes", "review_notes", "closed_reason",
)
PHOTO_FIELDS = ("photos", "warehouse_photos", "no_pickup_photos", "driver_photos")
ROUTE_FIELDS = ("route_id", "route_number")
DRIVER_FIELDS = (
    "assigned_driver", "driver_phone", "driver_status", "driver_work_status",
    "collected_racks", "collected_pieces", "driver_count_revisions",
    "driver_exception_type", "driver_exception_notes",
)
RECOVERY_FIELDS = (
    "corner_posts", "drb40", "drb48", "wood_shelf", "recovered_at",
    "recovery_status", "rms_status",
)
RECEIVING_FIELDS = (
    "receiving_status", "received_by", "received_at", "warehouse_verified_racks",
    "warehouse_verified_pieces", "warehouse_verified_counts", "damage_counts",
    "dispatcher_closeout_status",
)
INVENTORY_FIELDS = ("inventory_transaction_id", "inventory_adjustments", "inventory_updated_at")
FULFILLMENT_FIELDS = ("fulfillment_orders",)


def any_present(record, fields):
    for field in fields:
        value = record.get(field)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (int, float)) and value == 0:
            continue
        return True
    return False


def record_signals(record, routes=None, audit_entries=None):
    routes = routes or []
    audit_entries = audit_entries or []
    record_id = clean(record.get("id"))
    bol = normalize_bol_number(record.get("bol"))
    linked_routes = [
        route for route in routes
        if record_id and (
            record_id in (route.get("store_ids") or [])
            or any(clean(stop.get("id")) == record_id for stop in route.get("stops") or [] if isinstance(stop, dict))
        )
    ]
    audit_hits = [
        item for item in audit_entries
        if bol and bol in normalize_bol_number(json.dumps(item, default=str))
    ]
    return {
        "route_linked": bool(any_present(record, ROUTE_FIELDS) or linked_routes),
        "driver_progress": any_present(record, DRIVER_FIELDS),
        "recovery_data": any_present(record, RECOVERY_FIELDS),
        "receiving_verified": any_present(record, RECEIVING_FIELDS),
        "inventory_effect": any_present(record, INVENTORY_FIELDS),
        "fulfillment_effect": any_present(record, FULFILLMENT_FIELDS),
        "photos": any_present(record, PHOTO_FIELDS),
        "notes": any_present(record, NOTE_FIELDS),
        "timestamps": any_present(record, OPERATIONAL_TIMESTAMP_FIELDS),
        "audit_history": bool(audit_hits),
        "completed_or_closed": clean(record.get("status")).lower() in {"completed", "closed", "recovered"}
            or clean(record.get("rms_status")).lower() in {"closed by rms", "closed in rms", "missing from rms"},
        "linked_route_count": len(linked_routes),
        "audit_count": len(audit_hits),
    }


def completeness_score(record):
    score = 0
    for _, value in record.items():
        if value not in (None, "", [], {}):
            score += 1
    return score


def canonical_score(record, signals):
    score = 0
    if signals["route_linked"]:
        score += 1000
    if signals["driver_progress"]:
        score += 900
    if signals["recovery_data"]:
        score += 800
    if signals["receiving_verified"]:
        score += 700
    if signals["inventory_effect"] or signals["fulfillment_effect"]:
        score += 650
    if signals["completed_or_closed"]:
        score += 600
    if signals["photos"] or signals["notes"] or signals["timestamps"] or signals["audit_history"]:
        score += 500
    score += completeness_score(record)
    created = parse_time(record.get("created_at") or record.get("imported_at"))
    oldest_bonus = 0
    if created:
        oldest_bonus = max(0, int((datetime.now(created.tzinfo) - created).total_seconds() // 86400))
    return score, oldest_bonus


def choose_canonical(records, routes=None, audit_entries=None):
    enriched = []
    for record in records:
        signals = record_signals(record, routes, audit_entries)
        enriched.append((canonical_score(record, signals), record, signals))
    enriched.sort(key=lambda row: (row[0][0], row[0][1]), reverse=True)
    return enriched[0][1], {clean(row[1].get("id")): row[2] for row in enriched}


def classify_duplicate(record, canonical, signals, group_size):
    if clean(record.get("id")) == clean(canonical.get("id")):
        return "Canonical", "Preserve", "Selected as canonical record."
    if group_size <= 1:
        return "Uncertain", "Review", "Only stored record for this BOL."
    protected_reasons = []
    if signals["route_linked"]:
        protected_reasons.append("route-linked")
    if signals["driver_progress"]:
        protected_reasons.append("driver progress")
    if signals["receiving_verified"]:
        protected_reasons.append("receiving verification")
    if signals["inventory_effect"] or signals["fulfillment_effect"]:
        protected_reasons.append("inventory/fulfillment effect")
    if signals["completed_or_closed"]:
        protected_reasons.append("completed/closed history")
    if protected_reasons:
        return "Protected", "Preserve", "Protected operational data: " + ", ".join(protected_reasons) + "."
    merge_reasons = []
    if signals["recovery_data"]:
        merge_reasons.append("recovery/count data")
    if signals["photos"]:
        merge_reasons.append("photos")
    if signals["notes"]:
        merge_reasons.append("notes")
    if signals["audit_history"]:
        merge_reasons.append("audit history")
    if signals["timestamps"]:
        merge_reasons.append("operational timestamps")
    if merge_reasons:
        return "Merge Required", "Merge", "Duplicate has unique data: " + ", ".join(merge_reasons) + "."
    return "Safe Duplicate", "Remove", "No route, driver, recovery, receiving, inventory, fulfillment, notes, photos, audit, or timestamp data."


def duplicate_groups(stores, routes=None, audit_entries=None, rms_queue=None, sync_history=None):
    buckets = {}
    for record in stores or []:
        normalized = normalize_bol_number(record.get("bol"))
        if normalized:
            buckets.setdefault(normalized, []).append(record)

    groups = []
    for normalized, records in sorted(buckets.items()):
        if len(records) < 2:
            continue
        canonical, signals_by_id = choose_canonical(records, routes, audit_entries)
        rows = []
        for record in records:
            signals = signals_by_id.get(clean(record.get("id")), record_signals(record, routes, audit_entries))
            classification, action, reason = classify_duplicate(record, canonical, signals, len(records))
            rows.append({
                "record": safe_record_summary(record),
                "signals": signals,
                "classification": classification,
                "recommended_action": action,
                "reason": reason,
                "is_canonical": clean(record.get("id")) == clean(canonical.get("id")),
            })
        groups.append({
            "normalized_bol": normalized,
            "original_bol_values": sorted({clean(r.get("bol")) for r in records if clean(r.get("bol"))}),
            "record_ids": [clean(r.get("id")) for r in records],
            "statuses": sorted({clean(r.get("status")) for r in records if clean(r.get("status"))}),
            "canonical_record_id": clean(canonical.get("id")),
            "rows": rows,
            "rms_queue_refs": queue_refs(normalized, rms_queue),
            "sync_history_refs": history_refs(normalized, sync_history),
        })
    return groups


def queue_refs(normalized, queue):
    refs = []
    for item in queue or []:
        if normalize_bol_number(item.get("bol")) == normalized:
            refs.append({"bol": item.get("bol"), "status": item.get("queue_status") or item.get("status")})
    return refs


def history_refs(normalized, history):
    refs = []
    for item in history or []:
        text = json.dumps(item, default=str)
        if normalized in normalize_bol_number(text):
            refs.append({"time": item.get("time") or item.get("timestamp"), "status": item.get("status")})
    return refs[:10]


def safe_record_summary(record):
    return {
        "id": clean(record.get("id")),
        "bol": clean(record.get("bol")),
        "normalized_bol": normalize_bol_number(record.get("bol")),
        "status": clean(record.get("status")),
        "hub": clean(record.get("hub")),
        "route_id": clean(record.get("route_id")),
        "assigned_driver": clean(record.get("assigned_driver")),
        "receiving_status": clean(record.get("receiving_status")),
        "dispatcher_closeout_status": clean(record.get("dispatcher_closeout_status")),
        "pdf_present": bool(clean(record.get("pdf_path"))),
        "created_at": clean(record.get("created_at")),
        "updated_at": clean(record.get("updated_at")),
        "completed_at": clean(record.get("completed_at")),
    }


def scan_duplicate_bols(stores, routes=None, audit_entries=None, rms_queue=None, sync_history=None, last_cleanup=None):
    groups = duplicate_groups(stores, routes, audit_entries, rms_queue, sync_history)
    classifications = {"Safe Duplicate": 0, "Merge Required": 0, "Protected": 0, "Uncertain": 0}
    extra = 0
    for group in groups:
        extra += max(0, len(group["rows"]) - 1)
        for row in group["rows"]:
            if not row["is_canonical"] and row["classification"] in classifications:
                classifications[row["classification"]] += 1
    unique_bols = {normalize_bol_number(item.get("bol")) for item in stores or [] if normalize_bol_number(item.get("bol"))}
    return {
        "ok": True,
        "scan_time": datetime.now().isoformat(timespec="seconds"),
        "metrics": {
            "total_bol_records": len(stores or []),
            "unique_normalized_bols": len(unique_bols),
            "duplicate_groups": len(groups),
            "extra_duplicate_records": extra,
            "safe_duplicates": classifications["Safe Duplicate"],
            "merge_required_duplicates": classifications["Merge Required"],
            "protected_duplicates": classifications["Protected"],
            "uncertain_duplicates": classifications["Uncertain"],
            "last_cleanup_time": (last_cleanup or {}).get("cleanup_time", ""),
            "latest_backup_filename": (last_cleanup or {}).get("backup_manifest", {}).get("name", ""),
        },
        "groups": groups,
    }


def verify_json_file(path):
    path = Path(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload


def backup_runtime_files(files, backup_root, label="duplicate_bol_cleanup"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(backup_root) / f"{label}_{timestamp}_{uuid4().hex[:8]}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "name": backup_dir.name,
        "path": str(backup_dir),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "files": [],
    }
    for name, path in files.items():
        source = Path(path)
        destination = backup_dir / source.name
        if source.exists():
            shutil.copy2(source, destination)
        else:
            destination.write_text("[]" if name != "settings" else "{}", encoding="utf-8")
        payload = verify_json_file(destination)
        record_count = len(payload) if isinstance(payload, list) else len(payload.keys()) if isinstance(payload, dict) else 0
        unique_bol_count = 0
        duplicate_count = 0
        if name == "stores" and isinstance(payload, list):
            keys = [normalize_bol_number(item.get("bol")) for item in payload if normalize_bol_number(item.get("bol"))]
            unique_bol_count = len(set(keys))
            duplicate_count = max(0, len(keys) - unique_bol_count)
        manifest["files"].append({
            "name": source.name,
            "source_key": name,
            "size_bytes": destination.stat().st_size,
            "record_count": record_count,
            "unique_bol_count": unique_bol_count,
            "duplicate_count": duplicate_count,
        })
    (backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    verify_json_file(backup_dir / "manifest.json")
    return manifest


def cleanup_safe_duplicates(stores, routes=None, audit_entries=None, rms_queue=None, sync_history=None):
    scan = scan_duplicate_bols(stores, routes, audit_entries, rms_queue, sync_history)
    safe_ids = {
        row["record"]["id"]
        for group in scan["groups"]
        for row in group["rows"]
        if row["classification"] == "Safe Duplicate" and not row["is_canonical"]
    }
    kept = [record for record in stores if clean(record.get("id")) not in safe_ids]
    removed = [record for record in stores if clean(record.get("id")) in safe_ids]
    return kept, removed, scan


def find_latest_cleanup_manifest(backup_root):
    root = Path(backup_root)
    candidates = sorted(root.glob("duplicate_bol_cleanup_*/manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for manifest_path in candidates:
        try:
            manifest = verify_json_file(manifest_path)
            manifest["manifest_path"] = str(manifest_path)
            return manifest
        except Exception:
            continue
    return None


def restore_backup_manifest(manifest, files):
    manifest_dir = Path(manifest.get("manifest_path", manifest.get("path", ""))).parent if manifest.get("manifest_path") else Path(manifest["path"])
    restored = []
    for item in manifest.get("files") or []:
        key = item.get("source_key")
        if key not in files:
            continue
        backup_file = manifest_dir / item.get("name", "")
        payload = verify_json_file(backup_file)
        target = Path(files[key])
        tmp = target.with_suffix(target.suffix + ".rollback_tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        restored.append({"source_key": key, "target": target.name, "record_count": len(payload) if isinstance(payload, list) else 0})
    return restored
