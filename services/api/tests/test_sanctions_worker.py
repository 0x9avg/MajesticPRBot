from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

if "aio_pika" not in sys.modules:
    import types

    aio_pika_stub = types.ModuleType("aio_pika")
    aio_pika_stub.ExchangeType = SimpleNamespace(TOPIC="topic")
    aio_pika_stub.IncomingMessage = object

    async def _missing_aio_pika(*_args, **_kwargs):
        raise RuntimeError("aio_pika stub should not be called in sanctions worker tests")

    aio_pika_stub.connect_robust = _missing_aio_pika
    sys.modules["aio_pika"] = aio_pika_stub

import sanctions_worker as worker


MSK = timezone(timedelta(hours=3))
pytestmark = pytest.mark.anyio


class _FakeMessage:
    def __init__(self, body: bytes, *, headers: dict | None = None) -> None:
        self.body = body
        self.headers = headers or {}
        self.ack_count = 0
        self.nack_calls: list[dict[str, bool]] = []

    async def ack(self) -> None:
        self.ack_count += 1

    async def nack(self, *, requeue: bool = False) -> None:
        self.nack_calls.append({"requeue": requeue})


class _FakeDatabase:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True


class _FakeChannel:
    def __init__(self) -> None:
        self.is_closed = False
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        self.is_closed = True


class _FakeConnection:
    def __init__(self) -> None:
        self.is_closed = False
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        self.is_closed = True


def _fake_config_namespace() -> SimpleNamespace:
    return SimpleNamespace(
        validate_service_startup=lambda: None,
        db_host="localhost",
        db_port=3306,
        db_user="user",
        db_password="pass",
        db_name="db",
        setup_logging=lambda _name: SimpleNamespace(info=lambda *_a, **_k: None, error=lambda *_a, **_k: None),
    )


async def test_consume_issue_now_message_acks_and_drops_malformed_payload(monkeypatch) -> None:
    called = 0

    async def _unexpected(*_args, **_kwargs) -> None:
        nonlocal called
        called += 1

    monkeypatch.setattr(worker, "_process_issue_now", _unexpected)

    message = _FakeMessage(b"{not-json")

    await worker._consume_issue_now_message(SimpleNamespace(), message)

    assert called == 0
    assert message.ack_count == 1
    assert message.nack_calls == []


@pytest.mark.parametrize(
    ("payload", "label"),
    [
        ({}, "missing"),
        ({"operation_id": 0}, "zero"),
        ({"operation_id": "abc"}, "non-integer"),
    ],
)
async def test_consume_issue_now_message_acks_and_drops_invalid_operation_id(
    monkeypatch,
    payload: dict,
    label: str,
) -> None:
    called = 0

    async def _unexpected(*_args, **_kwargs) -> None:
        nonlocal called
        called += 1

    monkeypatch.setattr(worker, "_process_issue_now", _unexpected)

    message = _FakeMessage(json.dumps(payload).encode("utf-8"))

    await worker._consume_issue_now_message(SimpleNamespace(), message)

    assert called == 0, label
    assert message.ack_count == 1, label
    assert message.nack_calls == [], label


async def test_consume_issue_now_message_nacks_for_processing_exception(monkeypatch) -> None:
    async def _boom(*_args, **_kwargs) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "_process_issue_now", _boom)

    message = _FakeMessage(json.dumps({"operation_id": 123}).encode("utf-8"))

    await worker._consume_issue_now_message(SimpleNamespace(), message)

    assert message.ack_count == 0
    assert message.nack_calls == [{"requeue": True}]


async def test_consume_issue_now_message_dead_letters_poison_message_when_retry_budget_exhausted(
    monkeypatch,
) -> None:
    async def _boom(*_args, **_kwargs) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "_process_issue_now", _boom)

    message = _FakeMessage(
        json.dumps({"operation_id": 123}).encode("utf-8"),
        headers={"x-retry-count": 3},
    )

    await worker._consume_issue_now_message(SimpleNamespace(), message)

    assert message.ack_count == 0
    assert message.nack_calls == [{"requeue": False}]


async def test_main_processes_each_basis_date_only_once(monkeypatch) -> None:
    processed: list[datetime.date] = []
    sleep_calls = 0
    moments = [
        datetime(2026, 3, 19, 0, 5, tzinfo=MSK),
        datetime(2026, 3, 19, 0, 6, tzinfo=MSK),
    ]

    async def _process_day_stub(_database, basis_date) -> None:
        processed.append(basis_date)

    async def _sleep_stub(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise asyncio.CancelledError

    def _now(_tz=None):
        index = min(len(processed), len(moments) - 1)
        return moments[index]

    async def _run_broker_consumer_stub(_database):
        return _FakeConnection(), _FakeChannel()

    monkeypatch.setattr(worker, "Config", _fake_config_namespace())
    monkeypatch.setattr(worker, "Database", _FakeDatabase)
    monkeypatch.setattr(worker, "_process_day", _process_day_stub)
    monkeypatch.setattr(worker, "_run_broker_consumer", _run_broker_consumer_stub)
    monkeypatch.setattr(worker.asyncio, "sleep", _sleep_stub)
    monkeypatch.setattr(worker, "datetime", SimpleNamespace(now=_now))

    with pytest.raises(asyncio.CancelledError):
        await worker.main()

    assert processed == [datetime(2026, 3, 18).date()]


@pytest.mark.xfail(
    reason="nightly scheduler still processes pre-midnight because current gate is hour >= 0",
)
async def test_main_does_not_process_before_midnight_msk(monkeypatch) -> None:
    processed: list[datetime.date] = []
    sleep_calls = 0
    moment = datetime(2026, 3, 18, 23, 30, tzinfo=MSK)

    async def _process_day_stub(_database, basis_date) -> None:
        processed.append(basis_date)

    async def _sleep_stub(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        raise asyncio.CancelledError

    async def _run_broker_consumer_stub(_database):
        return _FakeConnection(), _FakeChannel()

    monkeypatch.setattr(worker, "Config", _fake_config_namespace())
    monkeypatch.setattr(worker, "Database", _FakeDatabase)
    monkeypatch.setattr(worker, "_process_day", _process_day_stub)
    monkeypatch.setattr(worker, "_run_broker_consumer", _run_broker_consumer_stub)
    monkeypatch.setattr(worker.asyncio, "sleep", _sleep_stub)
    monkeypatch.setattr(worker, "datetime", SimpleNamespace(now=lambda _tz=None: moment))

    with pytest.raises(asyncio.CancelledError):
        await worker.main()

    assert processed == []
