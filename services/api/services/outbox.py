from __future__ import annotations

import asyncio
import logging
from typing import Any


logger = logging.getLogger(__name__)

OUTBOX_BATCH_SIZE = 100
OUTBOX_RETRY_DELAY_SECONDS = 5
OUTBOX_STUCK_PROCESSING_AGE_SECONDS = 300
OUTBOX_POLL_INTERVAL_SECONDS = 2.0


def _database_supports_outbox(database: Any) -> bool:
    return all(
        hasattr(database, method_name)
        for method_name in (
            "enqueue_outbox_message",
            "requeue_stuck_outbox_messages",
            "list_pending_outbox_messages",
            "claim_outbox_message",
            "mark_outbox_message_sent",
            "mark_outbox_message_failed",
        )
    )


def outbox_enabled(app: Any) -> bool:
    database = getattr(getattr(app, "state", None), "database", None)
    return _database_supports_outbox(database)


async def publish_integration_event(
    app: Any,
    *,
    routing_key: str,
    payload: dict[str, Any],
) -> bool:
    database = getattr(app.state, "database", None)
    if _database_supports_outbox(database):
        await database.enqueue_outbox_message(routing_key, payload)
        await flush_broker_outbox(app, limit=1)
        return True

    broker = getattr(app.state, "broker", None)
    if broker is None:
        return False

    result = await broker.publish(routing_key, payload)
    return result is not False


async def flush_broker_outbox(app: Any, *, limit: int = OUTBOX_BATCH_SIZE) -> int:
    database = getattr(app.state, "database", None)
    broker = getattr(app.state, "broker", None)

    if not _database_supports_outbox(database) or broker is None:
        return 0

    # When the broker is disconnected we keep rows pending and let the loop retry.
    if getattr(broker, "exchange", None) is None:
        return 0

    await database.requeue_stuck_outbox_messages(
        max_age_seconds=OUTBOX_STUCK_PROCESSING_AGE_SECONDS
    )
    messages = await database.list_pending_outbox_messages(limit=max(1, int(limit)))

    delivered = 0
    for message in messages:
        message_id = int(message["id"])
        claimed = await database.claim_outbox_message(message_id)
        if not claimed:
            continue

        try:
            result = await broker.publish(
                str(message["routing_key"]),
                dict(message["payload"]),
            )
            if result is False:
                raise RuntimeError("broker.publish returned False")
        except Exception as exc:
            await database.mark_outbox_message_failed(
                message_id,
                error=str(exc),
                retry_delay_seconds=OUTBOX_RETRY_DELAY_SECONDS,
            )
            logger.warning(
                "Failed to deliver outbox message %s (%s): %s",
                message_id,
                message.get("routing_key"),
                exc,
            )
            continue

        await database.mark_outbox_message_sent(message_id)
        delivered += 1

    return delivered


async def outbox_relay_loop(app: Any) -> None:
    while True:
        try:
            await flush_broker_outbox(app)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Outbox relay iteration failed")
        await asyncio.sleep(OUTBOX_POLL_INTERVAL_SECONDS)
