"""Database maintenance utilities for EOMS.

These helpers are intentionally framework-light so they can be called from Flask
routes, scripts, or future scheduled jobs. They never delete PDF files during a
repair. Duplicate repair only removes duplicate JSON records after a backup is
created.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4


ACTIVE_STATUSES = {"Need Review", "Unassigned", "Assigned", "Dispatched"}
COMPLETED_STATUSES = {"Completed", "RMS Closed", "Closed"}
PDF_KEYS = ("pdf_path", "printable_path")
KEEP_TIMESTAMP_KEYS = (
    "created_at",
    "imported_at",
    "assigned_date",
    "updated_at",
    "last_seen",
    "last_seen_in_rms_at",
)


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def normalize_bol(value) -> str:
    """Normalize BOL values so duplicate checks use one consistent key."""
    value = clean(value).upper()
    return "".join(ch for ch in value if ch.isalnum() or ch in {"-", "_"})


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def backup_stores_json(stores_file: Path, backups_dir: Path, reason="database_repair") -> Path:
    """Create a timestamped stores.json backup and return its path."""
    stores_file = Path(stores_file)
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    if not stores_file.exists():
        raise FileNotFoundError(f"stores.json not found at {stores_file}")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backups_dir / f"stores_{timestamp}_{reason}.json"
    shutil.copy2(stores_file, backup_file)
    return backup_file


def _timestamp_value(record: dict):
    for key in KEEP_TIMESTAMP_KEYS:
        value = clean(record.get(key))
        if not value:
            continue
        for fmt in (None, "%m/%d/%Y", "%Y-%m-%d"):
            try:
                if fmt is None:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                return datetime.strptime(value, fmt).timestamp()
            except Exception:
                pass
    return None


def _record_sort_key(index_record):
    index, record = index_record
    stamp = _timestamp_value(record)
    return (stamp is None, stamp if stamp is not None else index, index)


def group_duplicate_bols(stores: list[dict]) -> dict[str, list[tuple[int, dict]]]:
    grouped: dict[str, list[tuple[int, dict]]] = {}
    for index, record in enumerate(stores):
        bol = normalize_bol(record.get("bol"))
        if not bol:
            continue
        grouped.setdefault(bol, []).append((index, record))
    return {bol: rows for bol, rows in grouped.items() if len(rows) > 1}


def pdf_paths_for_record(record: dict) -> list[Path]:
    paths = []
    for key in PDF_KEYS:
        value = clean(record.get(key))
        if value:
            paths.append(Path(value))
    return paths


def missing_pdf_records(stores: list[dict]) -> list[dict]:
    missing = []
    for record in stores:
        for path in pdf_paths_for_record(record):
            if not path.exists():
                missing.append({
                    "id": clean(record.get("id")),
                    "bol": clean(record.get("bol")),
                    "status": clean(record.get("status") or "Unassigned"),
                    "path": str(path),
                })
    return missing


def referenced_pdf_paths(stores: list[dict]) -> set[str]:
    refs = set()
    for record in stores:
        for path in pdf_paths_for_record(record):
            try:
                refs.add(str(path.resolve()).lower())
            except Exception:
                refs.add(str(path).lower())
    return refs


def orphan_pdf_files(stores: list[dict], search_roots: list[Path]) -> list[str]:
    refs = referenced_pdf_paths(stores)
    orphans = []
    for root in search_roots:
        root = Path(root)
        if not root.exists():
            continue
        for pattern in ("*.pdf", "*.html"):
            for path in root.rglob(pattern):
                try:
                    key = str(path.resolve()).lower()
                except Exception:
                    key = str(path).lower()
                if key not in refs:
                    orphans.append(str(path))
    return sorted(set(orphans))


def database_health(stores_file: Path, bol_dir: Path, upload_dir: Path | None = None) -> dict:
    """Return a read-only database health report."""
    start = time.time()
    stores = _read_json(Path(stores_file), [])
    if not isinstance(stores, list):
        stores = []

    duplicate_groups = group_duplicate_bols(stores)
    missing = missing_pdf_records(stores)
    search_roots = [Path(bol_dir)]
    if upload_dir:
        search_roots.append(Path(upload_dir))
    orphans = orphan_pdf_files(stores, search_roots)

    by_status = {}
    for record in stores:
        status = clean(record.get("status") or "Unassigned")
        by_status[status] = by_status.get(status, 0) + 1

    duplicate_records = sum(len(rows) - 1 for rows in duplicate_groups.values())
    status = "Healthy"
    warnings = []
    if duplicate_records:
        warnings.append(f"{duplicate_records} duplicate BOL records found")
    if missing:
        warnings.append(f"{len(missing)} referenced PDF files are missing")
    if orphans:
        warnings.append(f"{len(orphans)} orphan PDF/HTML files found")
    if warnings:
        status = "Warning"

    return {
        "records_scanned": len(stores),
        "total_stores": len(stores),
        "unique_bols": len({normalize_bol(s.get("bol")) for s in stores if normalize_bol(s.get("bol"))}),
        "need_review": by_status.get("Need Review", 0),
        "unassigned": by_status.get("Unassigned", 0),
        "assigned": by_status.get("Assigned", 0),
        "dispatched": by_status.get("Dispatched", 0),
        "completed": by_status.get("Completed", 0),
        "duplicate_bols": len(duplicate_groups),
        "duplicate_records": duplicate_records,
        "missing_pdfs": len(missing),
        "orphan_pdfs": len(orphans),
        "database_status": status,
        "warnings": warnings,
        "duplicate_examples": [
            {"bol": bol, "count": len(rows)} for bol, rows in sorted(duplicate_groups.items())[:25]
        ],
        "missing_pdf_examples": missing[:25],
        "orphan_pdf_examples": orphans[:25],
        "time_elapsed_seconds": round(time.time() - start, 2),
        "read_only": True,
    }


def _merge_duplicate_fields(keeper: dict, duplicate: dict) -> dict:
    """Preserve useful data from duplicate rows without overwriting keeper data."""
    for key, value in duplicate.items():
        if key == "id":
            continue
        if keeper.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
            keeper[key] = value
    keeper.setdefault("duplicate_record_ids_removed", [])
    dup_id = clean(duplicate.get("id"))
    if dup_id:
        keeper["duplicate_record_ids_removed"].append(dup_id)
    keeper["database_repaired_at"] = datetime.now().isoformat(timespec="seconds")
    return keeper


def repair_duplicate_bols(stores_file: Path, backups_dir: Path, bol_dir: Path, upload_dir: Path | None = None) -> dict:
    """Backup stores.json, remove duplicate BOL records, and save the cleaned DB.

    The oldest/first record for each BOL is kept. Missing PDFs are reported only;
    PDFs are never deleted by this function.
    """
    start = time.time()
    stores_file = Path(stores_file)
    backup_file = backup_stores_json(stores_file, Path(backups_dir), "before_database_repair")
    stores = _read_json(stores_file, [])
    if not isinstance(stores, list):
        raise ValueError("stores.json must contain a JSON list")

    records_scanned = len(stores)
    duplicate_groups = group_duplicate_bols(stores)
    remove_indexes = set()
    keep_by_bol = {}

    for bol, rows in duplicate_groups.items():
        sorted_rows = sorted(rows, key=_record_sort_key)
        keep_index, keeper = sorted_rows[0]
        keep_by_bol[bol] = keep_index
        for remove_index, duplicate in sorted_rows[1:]:
            _merge_duplicate_fields(keeper, duplicate)
            remove_indexes.add(remove_index)

    cleaned = [record for index, record in enumerate(stores) if index not in remove_indexes]
    _write_json_atomic(stores_file, cleaned)

    health_after = database_health(stores_file, bol_dir, upload_dir)
    report = {
        "ok": True,
        "backup_file": str(backup_file),
        "records_scanned": records_scanned,
        "records_after": len(cleaned),
        "unique_bols": health_after["unique_bols"],
        "duplicate_bols_before": len(duplicate_groups),
        "duplicates_removed": len(remove_indexes),
        "missing_pdfs": health_after["missing_pdfs"],
        "orphan_pdfs": health_after["orphan_pdfs"],
        "database_status": health_after["database_status"],
        "time_elapsed_seconds": round(time.time() - start, 2),
        "message": f"Database repair complete. Removed {len(remove_indexes)} duplicate records.",
    }
    return report


def upsert_record_by_bol(stores: list[dict], item: dict) -> tuple[list[dict], str]:
    """Update existing BOL record or append a new one. Returns (stores, action)."""
    bol = normalize_bol(item.get("bol"))
    now = datetime.now().isoformat(timespec="seconds")
    if not bol:
        item.setdefault("id", str(uuid4()))
        stores.append(item)
        return stores, "created_no_bol"

    for index, existing in enumerate(stores):
        if normalize_bol(existing.get("bol")) == bol:
            preserved = {}
            for key in (
                "id", "assigned_driver", "assigned_driver_phone", "assigned_at",
                "collected_racks", "collected_pieces", "variance", "pieces_variance",
                "completed_at", "closeout_updated_at", "closeout_updated_by",
            ):
                if existing.get(key) not in (None, "", [], {}):
                    preserved[key] = existing.get(key)
            if clean(existing.get("status")) in {"Assigned", "Dispatched", "Completed"}:
                preserved["status"] = existing.get("status")
            merged = dict(existing)
            merged.update(item)
            merged.update(preserved)
            merged["updated_at"] = now
            merged["last_seen_in_rms_at"] = now
            merged["rms_status"] = "Open in RMS"
            merged["rms_missing_since"] = ""
            stores[index] = merged
            return stores, "updated"

    item.setdefault("id", str(uuid4()))
    item.setdefault("created_at", now)
    item["updated_at"] = now
    item["last_seen_in_rms_at"] = now
    item["rms_status"] = "Open in RMS"
    item["rms_missing_since"] = ""
    stores.append(item)
    return stores, "created"
