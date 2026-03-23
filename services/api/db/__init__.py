from __future__ import annotations

from .assistant_weekly import AssistantWeeklyMixin
from .assistants import AssistantsMixin
from .audit import AuditMixin
from .auth_accounts import AuthAccountsMixin
from .bootstrap import BootstrapMixin
from .complaints import ComplaintsMixin
from .core import DatabaseCore, _week_start_msk
from .events import EventsMixin
from .guilds import GuildsMixin
from .outbox import OutboxMixin
from .removals import RemovalsMixin
from .reporting import ReportingMixin
from .returns import ReturnsMixin
from .sanctions_batches import SanctionsBatchesMixin
from .sanctions_policy import SanctionsPolicyMixin
from .sanctions_runtime import SanctionsRuntimeMixin
from .site_settings import SiteSettingsMixin
from .spec_runtime import SpecRuntimeMixin
from .streamers import StreamersMixin


class Database(
    BootstrapMixin,
    OutboxMixin,
    SiteSettingsMixin,
    AuthAccountsMixin,
    AuditMixin,
    ReportingMixin,
    GuildsMixin,
    SpecRuntimeMixin,
    StreamersMixin,
    EventsMixin,
    AssistantsMixin,
    ReturnsMixin,
    ComplaintsMixin,
    RemovalsMixin,
    SanctionsPolicyMixin,
    AssistantWeeklyMixin,
    SanctionsRuntimeMixin,
    SanctionsBatchesMixin,
    DatabaseCore,
):
    """Database facade assembled from domain mixins."""


__all__ = ['Database', '_week_start_msk']
