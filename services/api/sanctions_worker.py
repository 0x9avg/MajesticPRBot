"""Worker for nightly sanction queue processing and manual issue-now commands."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import aio_pika
from aio_pika import ExchangeType, IncomingMessage

from config import Config
from database import Database


MSK = timezone(timedelta(hours=3))
ISSUE_NOW_ROUTING_KEY = "sanction.operation.issue_now"
ISSUE_NOW_QUEUE_NAME = f"{Config.exchange_name}.sanctions_worker"
logger = Config.setup_logging("SanctionsWorker")


def _amqp_url() -> str:
    user = quote(Config.rabbitmq_user, safe="")
    password = quote(Config.rabbitmq_password, safe="")
    vhost = quote(Config.rabbitmq_vhost, safe="")
    return f"amqp://{user}:{password}@{Config.rabbitmq_host}:{Config.rabbitmq_port}/{vhost}"


async def _process_day(database: Database, basis_date):
    result = await database.process_queued_sanction_batches_for_date(basis_date)
    if result.get("skipped"):
        logger.info(
            "Skipped nightly sanctions for %s: status=%s",
            basis_date,
            (result.get("nightly_run") or {}).get("status"),
        )
        return
    logger.info(
        "Processed nightly sanctions for %s: batches=%s custom_workoff=%s auto_expired=%s relieved=%s month_reset=%s",
        basis_date,
        len(result.get("processed_batches") or []),
        len((result.get("custom_workoff") or {}).get("relieved") or []),
        len((result.get("warning_auto_expiry") or {}).get("relieved") or []),
        len((result.get("default_relief") or {}).get("relieved") or []),
        (result.get("month_reset") or {}).get("reset_count", 0),
    )


async def _process_issue_now(database: Database, payload: dict[str, Any]) -> None:
    operation_id = int(payload["operation_id"])
    requested_by_id = payload.get("requested_by_id")
    result = await database.process_sanction_operation_now(
        operation_id,
        requested_by_id=int(requested_by_id) if requested_by_id is not None else None,
    )
    logger.info(
        "Processed manual sanction issue_now for operation %s: processed=%s status=%s issued=%s failed=%s",
        operation_id,
        result.get("processed"),
        result.get("status"),
        len((result.get("issued") or [])),
        len((result.get("failed") or [])),
    )


async def _consume_issue_now_message(database: Database, message: IncomingMessage) -> None:
    try:
        payload = json.loads(message.body.decode("utf-8"))
    except Exception:
        logger.error("Dropping malformed sanctions worker message: %r", message.body)
        await message.ack()
        return

    try:
        if int(payload.get("operation_id")) <= 0:
            raise ValueError("operation_id is required")
    except Exception:
        logger.error("Dropping sanctions worker message without valid operation_id: %s", payload)
        await message.ack()
        return

    try:
        await _process_issue_now(database, payload)
    except Exception as exc:
        headers = getattr(message, "headers", {}) or {}
        try:
            retry_count = int(headers.get("x-retry-count") or 0)
        except Exception:
            retry_count = 0
        redelivered = bool(getattr(message, "redelivered", False))
        requeue = retry_count < 3 and not redelivered
        logger.error(
            "Failed to process manual sanction message for operation %s: %s",
            payload.get("operation_id"),
            exc,
            exc_info=True,
        )
        await message.nack(requeue=requeue)
        return

    await message.ack()


async def _run_broker_consumer(database: Database) -> tuple[aio_pika.RobustConnection, aio_pika.Channel]:
    connection = await aio_pika.connect_robust(_amqp_url())
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=8)
    exchange = await channel.declare_exchange(
        Config.exchange_name,
        ExchangeType.TOPIC,
        durable=True,
    )
    queue = await channel.declare_queue(
        ISSUE_NOW_QUEUE_NAME,
        durable=True,
    )
    await queue.bind(exchange, routing_key=ISSUE_NOW_ROUTING_KEY)
    await queue.consume(lambda message: _consume_issue_now_message(database, message))
    logger.info(
        "Sanctions worker subscribed to RabbitMQ queue %s via %s",
        ISSUE_NOW_QUEUE_NAME,
        ISSUE_NOW_ROUTING_KEY,
    )
    return connection, channel


async def main():
    Config.validate_service_startup()
    database = Database(
        db_host=Config.db_host,
        db_port=Config.db_port,
        db_user=Config.db_user,
        db_password=Config.db_password,
        db_name=Config.db_name,
        logger=Config.setup_logging("SanctionsWorkerDB"),
    )
    await database.start()
    connection = None
    channel = None
    logger.info("Sanctions worker started")

    last_attempted_basis_date = None
    try:
        connection, channel = await _run_broker_consumer(database)
        while True:
            now_msk = datetime.now(MSK)
            basis_date = now_msk.date() - timedelta(days=1)

            if basis_date != last_attempted_basis_date:
                try:
                    await _process_day(database, basis_date)
                    last_attempted_basis_date = basis_date
                except Exception as exc:
                    logger.error(
                        "Nightly sanctions processing failed for %s: %s",
                        basis_date,
                        exc,
                        exc_info=True,
                    )

            await asyncio.sleep(60)
    finally:
        try:
            if channel and not channel.is_closed:
                await channel.close()
        finally:
            if connection and not connection.is_closed:
                await connection.close()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
