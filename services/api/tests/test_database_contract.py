from __future__ import annotations

import inspect

from database import Database


def test_database_exposes_get_assistant_logs_coroutine() -> None:
    method = getattr(Database, "get_assistant_logs", None)

    assert method is not None
    assert inspect.iscoroutinefunction(method)
