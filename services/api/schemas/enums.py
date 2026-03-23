from enum import Enum

class SpecSessionEndReason(str, Enum):
    MANUAL_UNCLAIM = "manual_unclaim"
    STREAM_END = "stream_end"
    CATEGORY_CHANGE = "category_change"
    ADMIN_CLOSED = "admin_closed"
    EVENT_END = "event_end"
    EVENT_REJECTED = "event_rejected"
    UNKNOWN = "unknown"


class PunishmentType(str, Enum):
    JAIL = "jail"
    MUTE = "mute"


class ReturnRemoveReason(str, Enum):
    STREAM = "На стрим"
    VIDEO = "На видео"


class PunishmentReturnStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"


class WorkflowTargetStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"


class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ISSUED = "issued"


class ComplaintStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ISSUED = "issued"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ComplaintPunishmentType(str, Enum):
    MUTE = "mute"
    AJAIL = "ajail"
    WARN = "warn"
    BAN = "ban"
    HARDBAN = "hardban"
    GUNBAN = "gunban"


class PunishmentRemovalType(str, Enum):
    UNJAIL = "unjail"
    UNMUTE = "unmute"


class PunishmentRemovalReason(str, Enum):
    VIDEO = "На видео"
    STREAM = "На стрим"
