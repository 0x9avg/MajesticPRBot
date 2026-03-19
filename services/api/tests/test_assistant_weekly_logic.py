from __future__ import annotations

import logging
from datetime import date

from database import Database, _week_start_msk


def _database() -> Database:
    return Database(
        db_host="localhost",
        db_port=3306,
        db_user="user",
        db_password="password",
        db_name="test",
        logger=logging.getLogger("weekly-tests"),
    )


def _day(
    *,
    spec: float,
    mchat: int,
    complaints: int,
    norm_spec: float = 4.0,
    norm_mchat: int = 1,
    norm_complaints: int = 1,
    status: str | None = None,
) -> dict[str, object]:
    return {
        "resolved_status": status,
        "spec_hours": spec,
        "mchat_count": mchat,
        "complaints_count": complaints,
        "daily_norm_spec": norm_spec,
        "daily_norm_mchat": norm_mchat,
        "daily_norm_complaints": norm_complaints,
    }


def test_week_start_normalizes_to_monday() -> None:
    assert _week_start_msk(date(2026, 3, 19)) == date(2026, 3, 16)
    assert _week_start_msk(date(2026, 3, 16)) == date(2026, 3, 16)
    assert _week_start_msk(date(2026, 3, 22)) == date(2026, 3, 16)


def test_calculate_weekly_suggested_result_covers_all_primary_states() -> None:
    db = _database()

    inactive = db._calculate_weekly_suggested_result(
        active_day_records=[_day(spec=4, mchat=0, complaints=0) for _ in range(7)],
        total_spec_hours=28.0,
        total_mchat=0,
        total_complaints=0,
        count_p=0,
        count_o=0,
    )
    assert inactive["suggested_result"] == "Инактив"

    mixed = db._calculate_weekly_suggested_result(
        active_day_records=[_day(spec=4, mchat=1, complaints=0) for _ in range(7)],
        total_spec_hours=28.0,
        total_mchat=7,
        total_complaints=0,
        count_p=2,
        count_o=0,
    )
    assert mixed["suggested_result"] == "Инактив/Актив"

    active = db._calculate_weekly_suggested_result(
        active_day_records=[_day(spec=4, mchat=1, complaints=1) for _ in range(7)],
        total_spec_hours=28.0,
        total_mchat=7,
        total_complaints=7,
        count_p=1,
        count_o=0,
    )
    assert active["suggested_result"] == "Актив"

    ultra = db._calculate_weekly_suggested_result(
        active_day_records=[_day(spec=4, mchat=1, complaints=1) for _ in range(7)],
        total_spec_hours=42.0,
        total_mchat=7,
        total_complaints=7,
        count_p=0,
        count_o=0,
    )
    assert ultra["suggested_result"] == "Ультра-Актив"


def test_calculate_weekly_suggested_result_returns_unconfigured_when_norm_missing() -> None:
    db = _database()

    result = db._calculate_weekly_suggested_result(
        active_day_records=[_day(spec=4, mchat=1, complaints=1, norm_complaints=0)],
        total_spec_hours=4.0,
        total_mchat=1,
        total_complaints=1,
        count_p=0,
        count_o=0,
    )

    assert result["suggested_result"] is None
    assert result["suggested_reason"] == "unconfigured"


def test_build_weekly_payout_preview_uses_backend_amount_rules() -> None:
    db = _database()
    payout_config = {
        "type_command_map": {
            "EXP": "giveexp",
            "Premium": "setvip",
            "MC": "givedonate",
            "MONEY": "givemoney",
        },
        "amount_map": {
            ("default", "MONEY", "Актив"): "200000",
            ("junior", "MONEY", "Актив"): "150000",
        },
    }

    preview = db._build_weekly_payout_preview(
        assistant_role="employee",
        selected_result="Актив",
        payout_type="MONEY",
        payout_server="RU1",
        payout_static="static",
        payout_config=payout_config,
    )

    assert preview["command_available"] is True
    assert preview["amount"] == "200000"
    assert preview["command"] == "RU1:givemoney static 200000 pr-assist_byStynee"
