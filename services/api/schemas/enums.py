from enum import Enum

class SpecSessionEndReason(str, Enum):
    MANUAL_UNCLAIM = "manual_unclaim"
    STREAM_END = "stream_end"
    CATEGORY_CHANGE = "category_change"
    ADMIN_CLOSED = "admin_closed"
    EVENT_END = "event_end"
    EVENT_REJECTED = "event_rejected"
    UNKNOWN = "unknown"
