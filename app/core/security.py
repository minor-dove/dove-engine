"""
Security and privacy guard module.
Enforces edge privacy rules (rejecting camera/image payloads) and timestamp freshness.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Set, Optional

# Forbidden keys that would indicate raw camera or facial embedding data
FORBIDDEN_PRIVACY_KEYS: Set[str] = {
    "image",
    "images",
    "frame",
    "frames",
    "camera",
    "video",
    "face",
    "faces",
    "face_embedding",
    "face_embeddings",
    "embedding_raw",
    "raw_data",
    "base64_image",
    "photo",
    "snapshot",
    "jpeg",
    "png",
    "b64"
}


class PrivacyViolationError(Exception):
    """Raised when incoming payload contains prohibited camera, image, or raw facial data."""
    pass


def inspect_payload_for_privacy_violation(data: Any, path: str = "") -> None:
    """
    Recursively inspects incoming payloads to guarantee no camera, video, image,
    or raw facial embedding data is accepted or stored on the backend.
    
    Raises:
        PrivacyViolationError: If any forbidden privacy key is detected.
    """
    if isinstance(data, dict):
        for key, value in data.items():
            normalized_key = key.lower().replace("-", "_").strip()
            if normalized_key in FORBIDDEN_PRIVACY_KEYS:
                raise PrivacyViolationError(
                    f"Privacy violation: Forbidden key '{key}' detected in payload. "
                    "DOVE backend strictly prohibits receiving camera images, video, or face embeddings."
                )
            inspect_payload_for_privacy_violation(value, f"{path}.{key}" if path else key)
    elif isinstance(data, list):
        for index, item in enumerate(data):
            inspect_payload_for_privacy_violation(item, f"{path}[{index}]")


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensures datetime is timezone-aware in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_timestamp_fresh(
    event_timestamp: datetime,
    max_age_seconds: int = 1800,
    max_future_skew_seconds: int = 60
) -> bool:
    """
    Validates whether an event timestamp is within acceptable freshness limits.
    Prevents stale or replayed events from falsely altering state.
    """
    now = datetime.now(timezone.utc)
    event_timestamp = ensure_utc(event_timestamp)
        
    diff = (now - event_timestamp).total_seconds()
    
    # If the event is from the future beyond allowed clock skew
    if diff < -max_future_skew_seconds:
        return False
        
    # If the event is older than the allowed max age
    if diff > max_age_seconds:
        return False
        
    return True
