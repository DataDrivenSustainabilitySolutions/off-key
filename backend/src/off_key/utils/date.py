from datetime import datetime, timezone, timedelta
from urllib.parse import quote


def get_date_range(retention_days: int):
    # Get current UTC time
    now = datetime.now(timezone.utc)
    past = now - timedelta(days=retention_days)

    # Format as ISO 8601 string with 'Z' for UTC
    now_iso_ts = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"
    past_iso_ts = past.strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-3] + "Z"

    # URL encode the timestamps
    return "?StartDate=" + quote(past_iso_ts) + "&EndDate=" + quote(now_iso_ts)
