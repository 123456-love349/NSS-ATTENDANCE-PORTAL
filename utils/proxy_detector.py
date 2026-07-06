"""
utils/proxy_detector.py
Heuristic ("AI") proxy-attendance and risk-scoring engine.
"""

from datetime import datetime, timedelta
import math
from utils.location import haversine_distance_meters


def compute_rapid_submission_flag(db, ip_address, window_seconds=30, max_allowed=1):
    """True if this IP has already submitted attendance `max_allowed` times
    within the last `window_seconds` -- a signal of scripted/bulk proxying."""
    if not ip_address or ip_address == "unknown":
        return False
    cutoff = (datetime.utcnow() - timedelta(seconds=window_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    row = db.execute(
        """SELECT COUNT(*) AS c FROM attendance
           WHERE ip_address = ? AND created_at >= ?""",
        (ip_address, cutoff),
    ).fetchone()
    return row["c"] > max_allowed


def detect_same_device(db, ip_address, browser, device, event_id):
    """Check if multiple different students have logged attendance for the same
    event using the exact same device and IP footprint."""
    if not ip_address or ip_address == "unknown" or not event_id:
        return False, 0
    
    row = db.execute(
        """SELECT COUNT(DISTINCT COALESCE(crn, urn)) AS c FROM attendance
           WHERE event_id = ? AND ip_address = ? AND browser = ? AND device = ?""",
        (event_id, ip_address, browser, device),
    ).fetchone()
    count = row["c"] if row else 0
    # If more than 2 distinct students checked in from the same device, flag it.
    return count > 2, count


def detect_impossible_travel(db, crn, urn, current_lat, current_lon, current_time_str):
    """Check if a student's check-in implies travel speed > 80 km/h from their
    last recorded attendance location."""
    if not current_lat or not current_lon or not (crn or urn):
        return False, 0.0
    
    query = """SELECT latitude, longitude, created_at FROM attendance
               WHERE (crn = ? OR urn = ?) AND latitude IS NOT NULL AND longitude IS NOT NULL
               ORDER BY created_at DESC LIMIT 1"""
    prev = db.execute(query, (crn or None, urn or None)).fetchone()
    if not prev:
        return False, 0.0
        
    try:
        # Parse times
        fmt = "%Y-%m-%d %H:%M:%S"
        # strip fractional seconds if present
        prev_t_str = prev["created_at"].split(".")[0]
        curr_t_str = current_time_str.split(".")[0]
        
        prev_time = datetime.strptime(prev_t_str, fmt)
        curr_time = datetime.strptime(curr_t_str, fmt)
    except Exception:
        # If parsing fails, fall back to current time comparison
        return False, 0.0
        
    time_diff = abs((curr_time - prev_time).total_seconds())
    if time_diff <= 0:
        return False, 0.0
        
    dist_m = haversine_distance_meters(current_lat, current_lon, prev["latitude"], prev["longitude"])
    if dist_m is None or dist_m < 500:
        # Ignore small movements under 500m
        return False, 0.0
        
    speed_mps = dist_m / time_diff
    speed_kmh = speed_mps * 3.6
    
    # Flag if speed exceeds 80 km/h
    return speed_kmh > 80.0, speed_kmh


def compute_risk_score(config, *, is_duplicate, is_location_suspicious,
                         has_location, is_rapid_submission, is_same_device,
                         is_impossible_travel, is_poor_accuracy):
    score = 0
    if is_duplicate:
        score += config.get("RISK_WEIGHT_DUPLICATE", 40)
    if is_location_suspicious:
        score += config.get("RISK_WEIGHT_PROXY_LOCATION", 30)
    if not has_location:
        score += config.get("RISK_WEIGHT_NO_LOCATION", 20)
    if is_rapid_submission:
        score += config.get("RISK_WEIGHT_RAPID_SUBMISSION", 10)
    if is_same_device:
        score += 20  # same device heuristic
    if is_impossible_travel:
        score += 40  # impossible travel heuristic
    if is_poor_accuracy:
        score += 15  # poor GPS accuracy
    return min(score, 100)


def is_high_risk(risk_score, threshold=50):
    return risk_score >= threshold


def raise_alert(db, alert_type, attendance_id, message, severity="medium"):
    db.execute(
        """INSERT INTO ai_alerts (alert_type, attendance_id, message, severity)
           VALUES (?, ?, ?, ?)""",
        (alert_type, attendance_id, message, severity),
    )

