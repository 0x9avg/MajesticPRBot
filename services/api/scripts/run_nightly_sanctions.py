"""
One-shot CLI to manually trigger the nightly sanctions issuance flow.

This calls the same database path that `sanctions_worker.py` uses after 00:00 MSK:
`Database.process_queued_sanction_batches_for_date(...)`.

Examples:
  python scripts/run_nightly_sanctions.py
  python scripts/run_nightly_sanctions.py --date 2026-03-18
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv


API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, API_DIR)

from config import Config
from db import Database


MSK = timezone(timedelta(hours=3))


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def _default_basis_date() -> date:
    return datetime.now(MSK).date() - timedelta(days=1)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manually run the nightly sanctions issuance pass that normally "
            "starts after 00:00 MSK."
        )
    )
    parser.add_argument(
        "--date",
        "--basis-date",
        dest="basis_date",
        type=_parse_date,
        default=_default_basis_date(),
        help=(
            "Date to process sanctions for. Default: yesterday in MSK, which "
            "matches the worker's after-midnight behavior."
        ),
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print JSON result in compact form.",
    )
    return parser


async def _run_nightly_pass(*, basis_date: date) -> dict[str, Any]:
    Config.validate_database_config()
    logger = Config.setup_logging("RunNightlySanctions")
    database = Database(
        db_host=Config.db_host,
        db_port=Config.db_port,
        db_user=Config.db_user,
        db_password=Config.db_password,
        db_name=Config.db_name,
        logger=Config.setup_logging("RunNightlySanctionsDB"),
    )

    try:
        logger.info(
            "Starting one-shot nightly sanctions run for basis_date=%s",
            basis_date.isoformat(),
        )
        await database.start()
        result = await database.process_queued_sanction_batches_for_date(
            basis_date,
            force=True,
        )
        logger.info(
            "Finished one-shot nightly sanctions run for basis_date=%s: batches=%s custom_workoff=%s auto_expired=%s relieved=%s month_reset=%s skipped=%s",
            basis_date.isoformat(),
            len(result.get("processed_batches") or []),
            len((result.get("custom_workoff") or {}).get("relieved") or []),
            len((result.get("warning_auto_expiry") or {}).get("relieved") or []),
            len((result.get("default_relief") or {}).get("relieved") or []),
            (result.get("month_reset") or {}).get("reset_count", 0),
            result.get("skipped"),
        )
        return result
    finally:
        await database.close()


async def _main() -> int:
    load_dotenv(os.path.join(API_DIR, ".env"))
    args = _build_parser().parse_args()
    result = await _run_nightly_pass(basis_date=args.basis_date)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            default=_json_default,
            separators=(",", ":") if args.compact else None,
            indent=None if args.compact else 2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
