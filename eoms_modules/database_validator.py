def is_missing(value):
    return value is None or str(value).strip() == ""


def validate_records(records):
    report = {
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

    return report