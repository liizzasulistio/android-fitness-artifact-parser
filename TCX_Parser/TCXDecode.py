import sys
import json
import xml.etree.ElementTree as ET


def clean_tcx(file_path):
    f = open(file_path, "rb")
    data = f.read()
    f.close()

    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]

    data = data.lstrip()
    return data


def _ns_map():
    return {
        "tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
        "ns2": "http://www.garmin.com/xmlschemas/ActivityExtension/v2",
        "ns3": "http://www.garmin.com/xmlschemas/ActivityExtension/v2",
        "ns1": "http://www.garmin.com/xmlschemas/ExerciseIntensity/v2",
    }


def _text(node):
    if node is None or node.text is None:
        return None
    return node.text.strip()


def _text_to_float(node):
    try:
        if node is None or node.text is None:
            return None
        return float(node.text)
    except:
        return None


def _text_to_int(node):
    try:
        if node is None or node.text is None:
            return None
        return int(float(node.text))
    except:
        return None


def _find_first_text(parent, paths, ns=None):
    for path in paths:
        try:
            node = parent.find(path, ns) if ns else parent.find(path)
            val = _text(node)
            if val is not None and val != "":
                return val
        except:
            pass
    return None


def _find_first_float(parent, paths, ns=None):
    for path in paths:
        try:
            node = parent.find(path, ns) if ns else parent.find(path)
            val = _text_to_float(node)
            if val is not None:
                return val
        except:
            pass
    return None


def _find_first_int(parent, paths, ns=None):
    for path in paths:
        try:
            node = parent.find(path, ns) if ns else parent.find(path)
            val = _text_to_int(node)
            if val is not None:
                return val
        except:
            pass
    return None


def _parse_trackpoint(tp, ns):
    timestamp = _find_first_text(tp, [
        "tcx:Time",
        "{*}Time"
    ], ns)

    alt = _find_first_float(tp, [
        "tcx:AltitudeMeters",
        "{*}AltitudeMeters"
    ], ns)

    hr = _find_first_int(tp, [
        "tcx:HeartRateBpm/tcx:Value",
        "{*}HeartRateBpm/{*}Value"
    ], ns)

    cadence = _find_first_int(tp, [
        "tcx:Cadence",
        "{*}Cadence"
    ], ns)

    speed_val = None
    ext = tp.find("tcx:Extensions", ns)
    if ext is None:
        ext = tp.find("{*}Extensions")

    if ext is not None:
        try:
            sp = ext.find(".//{*}Speed")
            if sp is not None and sp.text is not None:
                speed_val = float(sp.text)
        except:
            speed_val = None

    lat_val = None
    lon_val = None

    lat_val = _find_first_float(tp, [
        "tcx:Position/tcx:LatitudeDegrees",
        "{*}Position/{*}LatitudeDegrees"
    ], ns)

    lon_val = _find_first_float(tp, [
        "tcx:Position/tcx:LongitudeDegrees",
        "{*}Position/{*}LongitudeDegrees"
    ], ns)

    if (lat_val is None or lon_val is None) and ext is not None:
        lat2 = ext.find(".//{*}LatitudeDegrees")
        lon2 = ext.find(".//{*}LongitudeDegrees")
        if lat2 is not None and lon2 is not None:
            lat_val = _text_to_float(lat2)
            lon_val = _text_to_float(lon2)

    total_dist = _find_first_float(tp, [
        "tcx:DistanceMeters",
        "{*}DistanceMeters"
    ], ns)

    return {
        "timestamp": timestamp,
        "lat": lat_val,
        "lon": lon_val,
        "alt": alt,
        "hr": hr,
        "cadence": cadence,
        "speed": speed_val,
        "total_distance": total_dist
    }


def parse_tcx(file_path):
    xml_bytes = clean_tcx(file_path)
    ns = _ns_map()

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        return {"error": "TCX parse failed: " + str(e)}

    data = {
        "file": file_path,
        "summary": {},
        "gps": {},
        "trackpoints": []
    }

    activity = root.find(".//tcx:Activity", ns)
    if activity is None:
        activity = root.find(".//{*}Activity")

    sport = None
    creator_name = None

    if activity is not None:
        sport = activity.get("Sport") or activity.get("sport")

        creator_name = _find_first_text(activity, [
            "tcx:Creator/tcx:Name",
            "{*}Creator/{*}Name",
            "tcx:Creator",
            "{*}Creator"
        ], ns)

    laps = root.findall(".//tcx:Lap", ns)
    if not laps:
        laps = root.findall(".//{*}Lap")

    lap_count = len(laps)

    total_time_seconds = 0.0
    total_distance_m = 0.0
    total_calories = 0.0
    found_calories = False

    avg_hr_values = []
    max_hr_values = []
    cadence_values = []

    start_time = None

    for lap in laps:
        if start_time is None:
            start_time = lap.get("StartTime") or lap.get("startTime")

        t = _find_first_float(lap, [
            "tcx:TotalTimeSeconds",
            "{*}TotalTimeSeconds"
        ], ns)

        d = _find_first_float(lap, [
            "tcx:DistanceMeters",
            "{*}DistanceMeters"
        ], ns)

        c = _find_first_float(lap, [
            "tcx:Calories",
            "{*}Calories"
        ], ns)

        if t is not None:
            total_time_seconds += t
        if d is not None:
            total_distance_m += d
        if c is not None:
            total_calories += c
            found_calories = True

        avg_hr = _find_first_int(lap, [
            "tcx:AverageHeartRateBpm/tcx:Value",
            "{*}AverageHeartRateBpm/{*}Value"
        ], ns)

        max_hr = _find_first_int(lap, [
            "tcx:MaximumHeartRateBpm/tcx:Value",
            "{*}MaximumHeartRateBpm/{*}Value"
        ], ns)

        cad = _find_first_int(lap, [
            "tcx:Cadence",
            "{*}Cadence"
        ], ns)

        if avg_hr is not None:
            avg_hr_values.append(avg_hr)
        if max_hr is not None:
            max_hr_values.append(max_hr)
        if cad is not None:
            cadence_values.append(cad)

    trackpoints = []
    for tp in root.findall(".//tcx:Trackpoint", ns):
        trackpoints.append(_parse_trackpoint(tp, ns))

    if not trackpoints:
        for tp in root.findall(".//{*}Trackpoint"):
            trackpoints.append(_parse_trackpoint(tp, ns))

    data["trackpoints"] = trackpoints

    gps_points = []
    for tp in trackpoints:
        if tp.get("lat") is not None and tp.get("lon") is not None:
            gps_points.append((tp.get("lat"), tp.get("lon")))

    if gps_points:
        data["gps"]["start_lat"] = gps_points[0][0]
        data["gps"]["start_lon"] = gps_points[0][1]
        data["gps"]["end_lat"] = gps_points[-1][0]
        data["gps"]["end_lon"] = gps_points[-1][1]

    speed_values = []
    hr_values = []
    cadence_tp_values = []

    for tp in trackpoints:
        if tp.get("speed") is not None and tp.get("speed") > 0:
            speed_values.append(tp.get("speed"))
        if tp.get("hr") is not None:
            hr_values.append(tp.get("hr"))
        if tp.get("cadence") is not None:
            cadence_tp_values.append(tp.get("cadence"))

    average_heart_rate = None
    max_heart_rate = None
    average_cadence = None
    average_speed_kmh = None
    max_speed_kmh = None
    average_pace_min_per_km = None

    if hr_values:
        average_heart_rate = round(float(sum(hr_values)) / len(hr_values), 1)
        max_heart_rate = max(hr_values)
    else:
        if avg_hr_values:
            average_heart_rate = round(float(sum(avg_hr_values)) / len(avg_hr_values), 1)
        if max_hr_values:
            max_heart_rate = max(max_hr_values)

    if cadence_tp_values:
        average_cadence = round(float(sum(cadence_tp_values)) / len(cadence_tp_values), 1)
    elif cadence_values:
        average_cadence = round(float(sum(cadence_values)) / len(cadence_values), 1)

    if speed_values:
        average_speed_kmh = round((float(sum(speed_values)) / len(speed_values)) * 3.6, 2)
        max_speed_kmh = round(max(speed_values) * 3.6, 2)

    total_distance_km = None
    total_timer_time_min = None

    if total_distance_m > 0:
        total_distance_km = round(total_distance_m / 1000.0, 3)

    if total_time_seconds > 0:
        total_timer_time_min = round(total_time_seconds / 60.0, 2)

    if total_distance_km and total_timer_time_min and total_distance_km > 0:
        average_pace_min_per_km = round(total_timer_time_min / total_distance_km, 2)

    data["summary"] = {
        "sport": sport,
        "creator": creator_name,
        "start_time": start_time,
        "total_timer_time_min": total_timer_time_min,
        "total_distance_km": total_distance_km,
        "total_calories": round(total_calories, 2) if found_calories else None,
        "average_heart_rate": average_heart_rate,
        "max_heart_rate": max_heart_rate,
        "average_speed_kmh": average_speed_kmh,
        "max_speed_kmh": max_speed_kmh,
        "average_pace_min_per_km": average_pace_min_per_km,
        "average_cadence_spm": average_cadence,
        "lap_count": lap_count
    }

    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python TCXDecode.py <tcx_file>"}))
        sys.exit(1)

    path = sys.argv[1]
    out = parse_tcx(path)
    print(json.dumps(out, indent=2, ensure_ascii=False))