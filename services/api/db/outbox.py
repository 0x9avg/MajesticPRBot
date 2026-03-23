from __future__ import annotations

from .core import (
    Any,
    BROKER_OUTBOX_STATUS_PENDING,
    BROKER_OUTBOX_STATUS_PROCESSING,
    BROKER_OUTBOX_STATUS_SENT,
    Dict,
    List,
    Optional,
    _msk_now,
    aiomysql,
    json,
    timedelta,
)


class OutboxMixin:
    async def _enqueue_outbox_message_with_cursor(
        self,
        cursor,
        *,
        routing_key: str,
        payload: Dict[str, Any],
    ) -> int:
        await cursor.execute(
            """
            INSERT INTO broker_outbox (routing_key, payload)
            VALUES (%s, %s)
            """,
            (str(routing_key), json.dumps(payload, default=str)),
        )
        return int(cursor.lastrowid)

    async def _enqueue_outbox_messages_with_cursor(
        self,
        cursor,
        outbox_events: Optional[List[Dict[str, Any]]],
    ) -> List[int]:
        message_ids: List[int] = []
        for event in outbox_events or []:
            routing_key = str(event.get("routing_key") or "").strip()
            payload = event.get("payload")
            if not routing_key or not isinstance(payload, dict):
                continue
            message_id = await self._enqueue_outbox_message_with_cursor(
                cursor,
                routing_key=routing_key,
                payload=payload,
            )
            message_ids.append(message_id)
        return message_ids

    async def enqueue_outbox_message(self, routing_key: str, payload: Dict[str, Any]) -> int:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                message_id = await self._enqueue_outbox_message_with_cursor(
                    cursor,
                    routing_key=routing_key,
                    payload=payload,
                )
                await conn.commit()
                return message_id

    async def requeue_stuck_outbox_messages(self, *, max_age_seconds: int = 300) -> int:
        cutoff = _msk_now().replace(tzinfo=None) - timedelta(
            seconds=max(1, int(max_age_seconds))
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE broker_outbox
                    SET status = 'pending',
                        available_at = CURRENT_TIMESTAMP,
                        processing_started_at = NULL
                    WHERE status = 'processing'
                      AND processing_started_at IS NOT NULL
                      AND processing_started_at <= %s
                    """,
                    (cutoff,),
                )
                await conn.commit()
                return int(cursor.rowcount or 0)

    async def list_pending_outbox_messages(self, limit: int = 100) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    """
                    SELECT id, routing_key, payload, attempts, created_at
                    FROM broker_outbox
                    WHERE status = 'pending'
                      AND available_at <= CURRENT_TIMESTAMP
                    ORDER BY id ASC
                    LIMIT %s
                    """,
                    (max(1, int(limit)),),
                )
                rows = await cursor.fetchall() or []
                for row in rows:
                    payload = row.get("payload")
                    if isinstance(payload, str):
                        row["payload"] = json.loads(payload)
                return rows

    async def claim_outbox_message(self, message_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE broker_outbox
                    SET status = 'processing',
                        attempts = attempts + 1,
                        processing_started_at = CURRENT_TIMESTAMP,
                        last_error = NULL
                    WHERE id = %s
                      AND status = 'pending'
                      AND available_at <= CURRENT_TIMESTAMP
                    """,
                    (int(message_id),),
                )
                await conn.commit()
                return cursor.rowcount > 0

    async def mark_outbox_message_sent(self, message_id: int) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE broker_outbox
                    SET status = 'sent',
                        sent_at = CURRENT_TIMESTAMP,
                        processing_started_at = NULL,
                        last_error = NULL
                    WHERE id = %s
                    """,
                    (int(message_id),),
                )
                await conn.commit()
                return cursor.rowcount > 0

    async def mark_outbox_message_failed(
        self,
        message_id: int,
        *,
        error: str,
        retry_delay_seconds: int = 5,
    ) -> bool:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    UPDATE broker_outbox
                    SET status = 'pending',
                        available_at = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL %s SECOND),
                        processing_started_at = NULL,
                        last_error = %s
                    WHERE id = %s
                    """,
                    (max(1, int(retry_delay_seconds)), str(error)[:65535], int(message_id)),
                )
                await conn.commit()
                return cursor.rowcount > 0
