# -*- coding: utf-8 -*-
# FitDecode_v3.4.py
# Updated FIT file decoder for Autopsy module
# Uses fitdecode (modern library) with extended extraction and conversions

import sys
import json
import subprocess
from datetime import datetime

# --- Auto-install check ---
try:
    import fitdecode
except ImportError:
    try:
        print("Installing required module: fitdecode", file=sys.stderr)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "fitdecode"])
        import fitdecode
        print("fitdecode successfully installed.", file=sys.stderr)
    except Exception as e:
        print(json.dumps({"error": "Failed to install fitdecode", "details": str(e)}))
        sys.exit(1)


def safe_float(val):
    try:
        return float(val)
    except Exception:
        return None


def _clean_text(val):
    if val is None:
        return None
    try:
        val = str(val).strip()
        if val == "":
            return None
        return val
    except Exception:
        return None


def _build_creator_device(manufacturer=None, product=None, garmin_product=None):
    parts = []

    manufacturer = _clean_text(manufacturer)
    product = _clean_text(product)
    garmin_product = _clean_text(garmin_product)

    if manufacturer:
        parts.append(manufacturer)

    if product:
        parts.append(product)
    elif garmin_product:
        parts.append(garmin_product)

    if parts:
        return " ".join(parts)

    return None


def decode_fit(file_path):
    """
    Decode a FIT file and extract all possible information.
    """
    data = {
        "file_id": [],
        "device_info": [],
        "session": [],
        "lap": [],
        "record": [],
        "developer_data": [],
        "other": []
    }

    # read all frames
    with fitdecode.FitReader(file_path) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue

            msg = frame.name
            record = {}

            for field in frame.fields:
                record[field.name] = field.value

            # Developer data support
            dev_fields = []
            if hasattr(frame, "developer_fields"):
                dev_fields = frame.developer_fields or []
            elif hasattr(frame, "get_developer_fields"):
                dev_fields = frame.get_developer_fields() or []

            for dev_field in dev_fields:
                name = getattr(dev_field, "name", None) or "dev_{}".format(getattr(dev_field, "def_num", "?"))
                record[name] = getattr(dev_field, "value", None)

            if msg in data:
                data[msg].append(record)
            elif dev_fields:
                data["developer_data"].append(record)
            else:
                data["other"].append({msg: record})

    # Extract metadata summary
    summary = {}
    try:
        if data["session"]:
            s = data["session"][0]
            summary.update({
                "sport": s.get("sport"),
                "sub_sport": s.get("sub_sport"),
                "start_time": str(s.get("start_time")),
                "total_timer_time_min": round(safe_float(s.get("total_timer_time")) / 60, 2) if s.get("total_timer_time") else None,
                "total_distance_km": round(safe_float(s.get("total_distance")) / 1000, 3) if s.get("total_distance") else None,
                "total_calories": s.get("total_calories"),
                "average_heart_rate": s.get("avg_heart_rate"),
                "max_heart_rate": s.get("max_heart_rate"),
                "average_speed_kmh": round(safe_float(s.get("avg_speed")) * 3.6, 2) if s.get("avg_speed") else None,
                "max_speed_kmh": round(safe_float(s.get("max_speed")) * 3.6, 2) if s.get("max_speed") else None,
                "total_ascent_m": s.get("total_ascent"),
                "total_descent_m": s.get("total_descent"),
                "avg_temperature_c": s.get("avg_temperature")
            })
    except Exception as e:
        summary["error_extract_session"] = str(e)

    # Device info
    device_meta = {}
    creator_device = None

    try:
        for d in data.get("device_info", []):
            if "manufacturer" in d or "product" in d or "garmin_product" in d:
                device_meta = {
                    "manufacturer": d.get("manufacturer"),
                    "product": d.get("product"),
                    "serial_number": d.get("serial_number"),
                    "software_version": d.get("software_version"),
                }

                creator_device = _build_creator_device(
                    d.get("manufacturer"),
                    d.get("product"),
                    d.get("garmin_product")
                )
                break
    except Exception:
        pass

    # Fallback from file_id if device_info did not provide usable creator/device
    if not creator_device:
        try:
            for f in data.get("file_id", []):
                creator_device = _build_creator_device(
                    f.get("manufacturer"),
                    f.get("product"),
                    f.get("garmin_product")
                )
                if creator_device:
                    # fill missing metadata only if not already set
                    if "manufacturer" not in device_meta:
                        device_meta["manufacturer"] = f.get("manufacturer")
                    if "product" not in device_meta:
                        device_meta["product"] = f.get("product")
                    break
        except Exception:
            pass

    summary.update(device_meta)
    summary["creator_device"] = creator_device

    # Extract GPS start/end
    gps_info = {}
    try:
        lat_field = "position_lat"
        lon_field = "position_long"
        positions = [
            (r.get(lat_field), r.get(lon_field))
            for r in data.get("record", [])
            if r.get(lat_field) and r.get(lon_field)
        ]
        if positions:
            gps_info["start_lat"], gps_info["start_lon"] = positions[0]
            gps_info["end_lat"], gps_info["end_lon"] = positions[-1]
    except Exception:
        pass

    # Compute analytics
    parsed = {"file": file_path, "summary": summary, "gps": gps_info, "messages": data}
    parsed = compute_analytics(parsed)
    return parsed


# -----------------------------------------------------
# Compute analytics
# -----------------------------------------------------
def compute_analytics(parsed):
    records = parsed["messages"].get("record", [])
    summary = parsed.get("summary", {})
    if not records:
        dist = summary.get("total_distance")
        time_s = summary.get("total_timer_time")
        if dist and time_s and time_s > 0:
            dist_km = dist / 1000.0
            pace_min_per_km = (time_s / 60.0) / dist_km
            summary["total_distance_km"] = round(dist_km, 3)
            summary["average_pace_min_per_km"] = round(pace_min_per_km, 2)
        parsed["summary"] = summary
        return parsed

    speeds = [r.get("speed") for r in records if r.get("speed")]
    hrs = [r.get("heart_rate") for r in records if r.get("heart_rate")]
    cadences = [r.get("cadence") for r in records if r.get("cadence")]

    analytics = {}
    if speeds:
        pace_values = [1000.0 / (s * 60.0) for s in speeds if s > 0]
        analytics["average_pace_min_per_km"] = round(sum(pace_values) / len(pace_values), 2)
        analytics["best_pace_min_per_km"] = round(min(pace_values), 2)
        analytics["slowest_pace_min_per_km"] = round(max(pace_values), 2)
        analytics["average_speed_kmh"] = round(sum(speeds) / len(speeds) * 3.6, 2)
        analytics["max_speed_kmh"] = round(max(speeds) * 3.6, 2)

    if cadences:
        analytics["average_cadence_spm"] = round(sum(cadences) / len(cadences), 1)

    if hrs:
        analytics["average_heart_rate"] = round(sum(hrs) / len(hrs), 1)
        analytics["max_heart_rate"] = max(hrs)

    dist = summary.get("total_distance")
    if dist:
        summary["total_distance_km"] = round(dist / 1000.0, 3)
        summary.pop("total_distance", None)

    if not summary.get("average_pace_min_per_km") and summary.get("total_timer_time") and summary.get("total_distance_km"):
        try:
            pace_min_per_km = (summary["total_timer_time"] / 60.0) / summary["total_distance_km"]
            summary["average_pace_min_per_km"] = round(pace_min_per_km, 2)
        except Exception:
            pass

    parsed["summary"] = summary
    parsed["analytics"] = analytics
    return parsed


# -----------------------------------------------------
# Main for Autopsy / CLI
# -----------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python FitDecode.py <fit_file>"}))
        sys.exit(1)

    fit_path = sys.argv[1]
    try:
        parsed = decode_fit(fit_path)
        parsed = compute_analytics(parsed)
        print(json.dumps(parsed, indent=2, default=str))

    except Exception as e:
        error_info = {
            "file": fit_path,
            "error": str(e),
            "type": e.__class__.__name__
        }
        try:
            import traceback
            error_info["traceback"] = traceback.format_exc()
        except Exception:
            pass

        print(json.dumps(error_info, indent=2))
        sys.exit(0)