from __future__ import annotations

from .core import (
    Any,
    Dict,
    List,
    MSK,
    Optional,
    WEEKLY_DAY_STATUS_VALUES,
    WEEKLY_MANUAL_STATUSES,
    WEEKLY_MANUAL_STATUS_NONE,
    WEEKLY_PAYOUT_AMOUNT_RULES,
    WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED,
    WEEKLY_PAYOUT_ISSUE_STATUS_PENDING,
    WEEKLY_PAYOUT_SUFFIX,
    WEEKLY_PAYOUT_TYPES,
    WEEKLY_SELECTED_RESULT_OPTIONS,
    WEEKLY_SELECTED_RESULTS,
    _canonical_weekly_payout_issue_status,
    _canonical_weekly_result,
    _date_only,
    _month_start,
    _msk_now,
    _msk_today,
    _week_dates,
    _week_start_msk,
    _weekly_role_group,
    date,
    datetime,
    db_retry,
    timedelta,
)


class AssistantWeeklyMixin:
    async def _get_weekly_payout_config_locked(self, cursor) -> Dict[str, Any]:
        await cursor.execute(
            """
            SELECT payout_type, command_name
            FROM assistant_weekly_payout_type_rules
            ORDER BY payout_type ASC
            """
        )
        type_rows = await cursor.fetchall() or []

        await cursor.execute(
            """
            SELECT role_group, payout_type, result_code, amount
            FROM assistant_weekly_payout_amount_rules
            """
        )
        amount_rows = await cursor.fetchall() or []

        await cursor.execute(
            """
            SELECT id, full_name, short_name, command_name, sort_order, is_active, created_at, updated_at
            FROM game_servers
            ORDER BY sort_order ASC, id ASC
            """
        )
        server_rows = await cursor.fetchall() or []

        return {
            "types": [
                {
                    "value": str(row.get("payout_type")),
                    "command_name": str(row.get("command_name") or ""),
                }
                for row in type_rows
            ],
            "type_command_map": {
                str(row.get("payout_type")): str(row.get("command_name") or "")
                for row in type_rows
                if row.get("payout_type")
            },
            "amount_map": {
                (
                    str(row.get("role_group")),
                    str(row.get("payout_type")),
                    str(row.get("result_code")),
                ): str(row.get("amount") or "")
                for row in amount_rows
                if row.get("role_group") and row.get("payout_type") and row.get("result_code")
            },
            "game_servers": [dict(row) for row in server_rows if row.get("id") is not None],
            "game_servers_by_id": {
                int(row.get("id")): dict(row)
                for row in server_rows
                if row.get("id") is not None
            },
            "selected_results": list(WEEKLY_SELECTED_RESULT_OPTIONS),
            "manual_statuses": list(WEEKLY_DAY_STATUS_VALUES),
        }

    def _build_weekly_payout_preview(
        self,
        *,
        assistant_role: Optional[str],
        selected_result: Optional[str],
        payout_type: Optional[str],
        payout_server_id: Optional[int],
        payout_static: Optional[str],
        payout_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        normalized_result = _canonical_weekly_result(selected_result)
        normalized_static = str(payout_static or "").strip() or None
        command_name = (
            payout_config.get("type_command_map", {}).get(str(payout_type))
            if payout_type
            else None
        )
        payout_server = None
        if payout_server_id is not None:
            payout_server = payout_config.get("game_servers_by_id", {}).get(int(payout_server_id))
        payout_server_name = str(payout_server.get("command_name") or "") if payout_server else None
        preview = {
            "type": payout_type,
            "server_id": payout_server_id,
            "static": normalized_static,
            "command_name": command_name,
            "amount": None,
            "command": None,
            "command_available": False,
            "command_unavailable_reason": None,
            "role_group": _weekly_role_group(assistant_role),
        }

        if normalized_result not in {"Актив", "Ультра-Актив"}:
            preview["command_unavailable_reason"] = "selected_result_not_payout_eligible"
            return preview
        if not payout_type or payout_server_id is None or not payout_server_name or not normalized_static:
            preview["command_unavailable_reason"] = "incomplete_payout_data"
            return preview
        if not command_name:
            preview["command_unavailable_reason"] = "payout_type_rule_missing"
            return preview

        amount = payout_config.get("amount_map", {}).get(
            (_weekly_role_group(assistant_role), str(payout_type), normalized_result)
        )
        if not amount:
            preview["command_unavailable_reason"] = "amount_rule_missing"
            return preview

        preview["amount"] = amount
        preview["command"] = (
            f"{payout_server_name}:{command_name} {normalized_static} {amount} {WEEKLY_PAYOUT_SUFFIX}"
        )
        preview["command_available"] = True
        return preview

    def _calculate_weekly_suggested_result(
        self,
        *,
        active_day_records: List[Dict[str, Any]],
        total_spec_hours: float,
        total_mchat: int,
        total_complaints: int,
        count_p: int,
        count_o: int,
    ) -> Dict[str, Any]:
        if not active_day_records:
            return {
                "suggested_result": None,
                "suggested_reason": "unconfigured",
                "metric_hits": 0,
                "weekly_norm_spec": 0.0,
                "weekly_norm_mchat": 0,
                "weekly_norm_complaints": 0,
            }

        if any(
            float(day.get("daily_norm_spec") or 0) <= 0
            or int(day.get("daily_norm_mchat") or 0) <= 0
            or int(day.get("daily_norm_complaints") or 0) <= 0
            for day in active_day_records
        ):
            return {
                "suggested_result": None,
                "suggested_reason": "unconfigured",
                "metric_hits": 0,
                "weekly_norm_spec": 0.0,
                "weekly_norm_mchat": 0,
                "weekly_norm_complaints": 0,
            }

        weekly_norm_spec = round(sum(float(day.get("daily_norm_spec") or 0) for day in active_day_records), 4)
        weekly_norm_mchat = int(sum(int(day.get("daily_norm_mchat") or 0) for day in active_day_records))
        weekly_norm_complaints = int(sum(int(day.get("daily_norm_complaints") or 0) for day in active_day_records))

        metric_hits = 0
        if total_spec_hours + 1e-9 >= weekly_norm_spec:
            metric_hits += 1
        if total_mchat >= weekly_norm_mchat:
            metric_hits += 1
        if total_complaints >= weekly_norm_complaints:
            metric_hits += 1

        ultra_daily_ok = all(
            (
                day.get("resolved_status") == "O"
                or (
                    float(day.get("spec_hours") or 0) + 1e-9 >= float(day.get("daily_norm_spec") or 0)
                    and int(day.get("mchat_count") or 0) >= int(day.get("daily_norm_mchat") or 0)
                    and int(day.get("complaints_count") or 0) >= int(day.get("daily_norm_complaints") or 0)
                )
            )
            for day in active_day_records
        )
        ultra_boosted = (
            total_spec_hours + 1e-9 >= round(weekly_norm_spec * 1.5, 4)
            or total_mchat >= weekly_norm_mchat * 2
            or total_complaints >= weekly_norm_complaints * 2
        )

        if count_p == 0 and count_o <= 1 and ultra_daily_ok and ultra_boosted:
            suggested_result = "Ультра-Актив"
        elif metric_hits == 3 and count_p <= 1:
            suggested_result = "Актив"
        elif metric_hits == 2 and count_p <= 2:
            suggested_result = "Инактив/Актив"
        else:
            suggested_result = "Инактив"

        return {
            "suggested_result": suggested_result,
            "suggested_reason": None,
            "metric_hits": metric_hits,
            "weekly_norm_spec": weekly_norm_spec,
            "weekly_norm_mchat": weekly_norm_mchat,
            "weekly_norm_complaints": weekly_norm_complaints,
        }

    async def _build_assistant_weekly_read_model_locked(
        self,
        cursor,
        *,
        week_start: date,
        assistant_id: Optional[int] = None,
        include_day_matrix: bool,
        include_payout_options: bool,
    ) -> Dict[str, Any]:
        normalized_week_start = _week_start_msk(week_start)
        week_end = normalized_week_start + timedelta(days=6)
        week_days = _week_dates(normalized_week_start)
        current_msk_date = _msk_today()
        roster_start_dt = datetime.combine(normalized_week_start, datetime.min.time())
        roster_end_exclusive = datetime.combine(week_end + timedelta(days=1), datetime.min.time())
        assistant_where = ""
        assistant_params: List[Any] = [roster_end_exclusive, roster_start_dt]
        if assistant_id is not None:
            assistant_where = " AND a.pr_id = %s"
            assistant_params.append(assistant_id)

        await cursor.execute(
            f"""
            SELECT
                a.pr_id,
                a.nickname,
                a.role,
                a.added_at,
                a.appointed_at,
                a.dismissed_at
            FROM assistants a
            WHERE COALESCE(a.appointed_at, a.added_at, CURRENT_TIMESTAMP) < %s
              AND (a.dismissed_at IS NULL OR a.dismissed_at >= %s)
              {assistant_where}
            ORDER BY a.nickname ASC, a.pr_id ASC
            """,
            tuple(assistant_params),
        )
        assistants = await cursor.fetchall() or []
        assistant_ids = [int(row.get("pr_id")) for row in assistants if row.get("pr_id") is not None]

        payout_config = await self._get_weekly_payout_config_locked(cursor)

        policy_by_month: Dict[date, Dict[str, Any]] = {}
        for month_start in sorted({_month_start(work_date) for work_date in week_days}):
            policy_by_month[month_start] = await self._ensure_monthly_policy_row(cursor, month_start)

        spec_map: Dict[tuple[int, date], Dict[str, Any]] = {}
        mchat_map: Dict[tuple[int, date], int] = {}
        complaints_map: Dict[tuple[int, date], int] = {}
        override_map: Dict[tuple[int, date], Dict[str, Any]] = {}
        review_map: Dict[int, Dict[str, Any]] = {}

        if assistant_ids:
            placeholders = ", ".join(["%s"] * len(assistant_ids))

            await cursor.execute(
                f"""
                SELECT assistant_id, work_date, spec_seconds_on_day, spec_hours_on_day, spec_points_auto
                FROM assistant_day_spec_totals
                WHERE assistant_id IN ({placeholders})
                  AND work_date BETWEEN %s AND %s
                """,
                (*assistant_ids, normalized_week_start, week_end),
            )
            for row in await cursor.fetchall() or []:
                work_date = row.get("work_date")
                if isinstance(work_date, datetime):
                    work_date = work_date.date()
                spec_map[(int(row.get("assistant_id") or 0), work_date)] = {
                    "spec_seconds_on_day": int(row.get("spec_seconds_on_day") or 0),
                    "spec_hours_on_day": round(float(row.get("spec_hours_on_day") or 0), 4),
                    "spec_points_auto": round(float(row.get("spec_points_auto") or 0), 4),
                }

            if normalized_week_start <= current_msk_date <= week_end:
                live_spec_map = await self._get_day_spec_metrics_map_locked(
                    cursor,
                    assistant_ids=assistant_ids,
                    work_date=current_msk_date,
                )
                for current_assistant_id, metrics in live_spec_map.items():
                    spec_map[(current_assistant_id, current_msk_date)] = metrics

            await cursor.execute(
                f"""
                SELECT assistant_id, work_date, mchat_count
                FROM assistant_day_mchat
                WHERE assistant_id IN ({placeholders})
                  AND work_date BETWEEN %s AND %s
                """,
                (*assistant_ids, normalized_week_start, week_end),
            )
            for row in await cursor.fetchall() or []:
                work_date = row.get("work_date")
                if isinstance(work_date, datetime):
                    work_date = work_date.date()
                mchat_map[(int(row.get("assistant_id") or 0), work_date)] = int(row.get("mchat_count") or 0)

            await cursor.execute(
                f"""
                SELECT assistant_id, DATE(COALESCE(issued_at, completed_at)) AS work_date, COUNT(*) AS complaints_count
                FROM complaints
                WHERE assistant_id IN ({placeholders})
                  AND status IN ('issued', 'completed')
                  AND DATE(COALESCE(issued_at, completed_at)) BETWEEN %s AND %s
                GROUP BY assistant_id, DATE(COALESCE(issued_at, completed_at))
                """,
                (*assistant_ids, normalized_week_start, week_end),
            )
            for row in await cursor.fetchall() or []:
                work_date = row.get("work_date")
                if isinstance(work_date, datetime):
                    work_date = work_date.date()
                if isinstance(work_date, str):
                    work_date = date.fromisoformat(work_date)
                complaints_map[(int(row.get("assistant_id") or 0), work_date)] = int(row.get("complaints_count") or 0)

            await cursor.execute(
                f"""
                SELECT assistant_id, work_date, manual_status, updated_at, updated_by_id
                FROM assistant_day_status_overrides
                WHERE assistant_id IN ({placeholders})
                  AND work_date BETWEEN %s AND %s
                """,
                (*assistant_ids, normalized_week_start, week_end),
            )
            for row in await cursor.fetchall() or []:
                work_date = row.get("work_date")
                if isinstance(work_date, datetime):
                    work_date = work_date.date()
                override_map[(int(row.get("assistant_id") or 0), work_date)] = {
                    "manual_status": row.get("manual_status"),
                    "updated_at": row.get("updated_at"),
                    "updated_by_id": row.get("updated_by_id"),
                }

            await cursor.execute(
                f"""
                SELECT
                    assistant_id,
                    selected_result,
                    payout_type,
                    payout_server_id,
                    payout_static,
                    payout_issue_status,
                    payout_issued_at,
                    payout_issued_by_id,
                    updated_at,
                    updated_by_id
                FROM assistant_weekly_reviews
                WHERE assistant_id IN ({placeholders})
                  AND week_start = %s
                """,
                (*assistant_ids, normalized_week_start),
            )
            for row in await cursor.fetchall() or []:
                review_map[int(row.get("assistant_id") or 0)] = dict(row)

        day_headers = [
            {
                "work_date": work_date,
                "weekday_index": index,
                "weekday_short": ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")[index],
                "label_short": work_date.strftime("%d.%m"),
            }
            for index, work_date in enumerate(week_days)
        ]

        items: List[Dict[str, Any]] = []
        for assistant in assistants:
            current_assistant_id = int(assistant.get("pr_id") or 0)
            appointed_date = _date_only(assistant.get("appointed_at") or assistant.get("added_at")) or normalized_week_start
            dismissed_date = _date_only(assistant.get("dismissed_at"))

            day_payloads: List[Dict[str, Any]] = []
            active_day_records: List[Dict[str, Any]] = []
            total_spec_hours = 0.0
            total_mchat = 0
            total_complaints = 0
            count_p = 0
            count_u = 0
            count_o = 0

            for index, work_date in enumerate(week_days):
                policy = policy_by_month[_month_start(work_date)]
                daily_norm_spec = round(float(policy.get("daily_norm_spec") or 0), 4)
                daily_norm_mchat = int(policy.get("daily_norm_mchat") or 0)
                daily_norm_complaints = int(policy.get("daily_norm_complaints") or 0)
                is_roster_day = work_date >= appointed_date and (dismissed_date is None or work_date <= dismissed_date)
                spec_metrics = spec_map.get(
                    (current_assistant_id, work_date),
                    {
                        "spec_seconds_on_day": 0,
                        "spec_hours_on_day": 0.0,
                        "spec_points_auto": 0.0,
                    },
                )
                spec_hours = round(float(spec_metrics.get("spec_hours_on_day") or 0), 4)
                mchat_count = int(mchat_map.get((current_assistant_id, work_date), 0))
                complaints_count = int(complaints_map.get((current_assistant_id, work_date), 0))
                override = override_map.get((current_assistant_id, work_date), {})
                has_manual_override = (current_assistant_id, work_date) in override_map
                raw_manual_status = override.get("manual_status")
                manual_status = None if raw_manual_status in (None, WEEKLY_MANUAL_STATUS_NONE) else raw_manual_status
                auto_status = None
                if is_roster_day and work_date < current_msk_date and daily_norm_spec > 0 and spec_hours + 1e-9 < daily_norm_spec:
                    auto_status = "P"
                resolved_status = manual_status if has_manual_override else auto_status
                status_source = "manual" if has_manual_override else ("auto" if auto_status else "none")

                if is_roster_day and resolved_status == "P":
                    count_p += 1
                elif is_roster_day and resolved_status == "U":
                    count_u += 1
                elif is_roster_day and resolved_status == "O":
                    count_o += 1

                total_spec_hours = round(total_spec_hours + spec_hours, 4)
                total_mchat += mchat_count
                total_complaints += complaints_count

                day_payload = {
                    "work_date": work_date,
                    "weekday_index": index,
                    "is_roster_day": is_roster_day,
                    "spec_seconds": int(spec_metrics.get("spec_seconds_on_day") or 0),
                    "spec_hours": spec_hours,
                    "mchat_count": mchat_count,
                    "complaints_count": complaints_count,
                    "daily_norm_spec": daily_norm_spec,
                    "daily_norm_mchat": daily_norm_mchat,
                    "daily_norm_complaints": daily_norm_complaints,
                    "manual_status": manual_status,
                    "auto_status": auto_status,
                    "resolved_status": resolved_status,
                    "status_source": status_source,
                    "manual_status_updated_at": override.get("updated_at"),
                    "manual_status_updated_by_id": override.get("updated_by_id"),
                }
                day_payloads.append(day_payload)
                if is_roster_day:
                    active_day_records.append(day_payload)

            suggestion = self._calculate_weekly_suggested_result(
                active_day_records=active_day_records,
                total_spec_hours=total_spec_hours,
                total_mchat=total_mchat,
                total_complaints=total_complaints,
                count_p=count_p,
                count_o=count_o,
            )
            review = review_map.get(current_assistant_id, {})
            selected_result = _canonical_weekly_result(review.get("selected_result"))
            payout_server_id = review.get("payout_server_id")
            payout = self._build_weekly_payout_preview(
                assistant_role=assistant.get("role"),
                selected_result=selected_result,
                payout_type=review.get("payout_type"),
                payout_server_id=int(payout_server_id) if payout_server_id is not None else None,
                payout_static=review.get("payout_static"),
                payout_config=payout_config,
            )
            payout_issue_status = _canonical_weekly_payout_issue_status(review.get("payout_issue_status"))

            item = {
                "assistant_id": current_assistant_id,
                "nickname": assistant.get("nickname"),
                "role": assistant.get("role"),
                "week_start": normalized_week_start,
                "week_end": week_end,
                "totals": {
                    "spec_hours": round(total_spec_hours, 4),
                    "mchat_count": total_mchat,
                    "complaints_count": total_complaints,
                },
                "counts": {
                    "P": count_p,
                    "U": count_u,
                    "O": count_o,
                },
                "suggested_result": suggestion.get("suggested_result"),
                "suggested_reason": suggestion.get("suggested_reason"),
                "suggestion_metrics": {
                    "metric_hits": suggestion.get("metric_hits"),
                    "weekly_norm_spec": suggestion.get("weekly_norm_spec"),
                    "weekly_norm_mchat": suggestion.get("weekly_norm_mchat"),
                    "weekly_norm_complaints": suggestion.get("weekly_norm_complaints"),
                },
                "selected_result": selected_result,
                "result_display": selected_result or suggestion.get("suggested_result"),
                "payout": payout,
                "payout_type": review.get("payout_type"),
                "payout_server_id": payout_server_id,
                "payout_static": review.get("payout_static"),
                "payout_issue_status": payout_issue_status,
                "payout_issued_at": review.get("payout_issued_at"),
                "payout_issued_by_id": review.get("payout_issued_by_id"),
                "review_updated_at": review.get("updated_at"),
                "review_updated_by_id": review.get("updated_by_id"),
            }
            if include_day_matrix:
                item["days"] = day_payloads
            items.append(item)

        payload = {
            "week_start": normalized_week_start,
            "week_end": week_end,
            "day_headers": day_headers,
            "items": items,
        }
        if include_payout_options:
            payload["payout_options"] = {
                "types": payout_config.get("types", []),
                "selected_results": payout_config.get("selected_results", []),
                "manual_statuses": payout_config.get("manual_statuses", []),
            }
        return payload

    @db_retry()
    async def get_current_assistant_weekly_overview(self) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                payload = await self._build_assistant_weekly_read_model_locked(
                    cursor,
                    week_start=_week_start_msk(),
                    include_day_matrix=True,
                    include_payout_options=False,
                )
                await conn.commit()
                return payload

    @db_retry()
    async def get_assistant_weekly_admin_overview(
        self,
        *,
        week_start: Optional[date] = None,
    ) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                payload = await self._build_assistant_weekly_read_model_locked(
                    cursor,
                    week_start=week_start or _week_start_msk(),
                    include_day_matrix=True,
                    include_payout_options=True,
                )
                await conn.commit()
                return payload

    @db_retry()
    async def get_assistant_weekly_admin_detail(
        self,
        *,
        assistant_id: int,
        week_start: Optional[date] = None,
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                payload = await self._build_assistant_weekly_read_model_locked(
                    cursor,
                    week_start=week_start or _week_start_msk(),
                    assistant_id=assistant_id,
                    include_day_matrix=True,
                    include_payout_options=True,
                )
                await conn.commit()
                if not payload.get("items"):
                    return None
                return {
                    "week_start": payload.get("week_start"),
                    "week_end": payload.get("week_end"),
                    "day_headers": payload.get("day_headers", []),
                    "payout_options": payload.get("payout_options", {}),
                    "detail": payload["items"][0],
                }

    @db_retry()
    async def save_assistant_weekly_admin_review(
        self,
        *,
        assistant_id: int,
        week_start: date,
        actor_id: Optional[int],
        day_overrides: List[Dict[str, Any]],
        selected_result: Optional[str],
        payout_type: Optional[str],
        payout_server_id: Optional[int],
        payout_static: Optional[str],
    ) -> Dict[str, Any]:
        normalized_week_start = _week_start_msk(week_start)
        week_end = normalized_week_start + timedelta(days=6)
        normalized_result = _canonical_weekly_result(selected_result)
        if normalized_result is not None and normalized_result not in WEEKLY_SELECTED_RESULTS:
            raise ValueError("Невалидный weekly result")
        if payout_type is not None and payout_type not in WEEKLY_PAYOUT_TYPES:
            raise ValueError("Невалидный payout type")
        normalized_static = str(payout_static or "").strip() or None
        payout_issue_transition = None

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT pr_id, role
                    FROM assistants
                    WHERE pr_id = %s
                      AND COALESCE(appointed_at, added_at, CURRENT_TIMESTAMP) < %s
                      AND (dismissed_at IS NULL OR dismissed_at >= %s)
                    LIMIT 1
                    """,
                    (
                        assistant_id,
                        datetime.combine(week_end + timedelta(days=1), datetime.min.time()),
                        datetime.combine(normalized_week_start, datetime.min.time()),
                    ),
                )
                assistant = await cursor.fetchone()
                if not assistant:
                    raise ValueError("Ассистент не найден")
                assistant_role = assistant.get("role")

                payout_config = await self._get_weekly_payout_config_locked(cursor)
                payout_server_row = None
                if payout_server_id is not None:
                    payout_server_row = payout_config.get("game_servers_by_id", {}).get(int(payout_server_id))
                    if payout_server_row is None:
                        raise ValueError("Невалидный payout server")

                await cursor.execute(
                    """
                    SELECT
                        selected_result,
                        payout_type,
                        payout_server_id,
                        payout_static,
                        payout_issue_status,
                        payout_issued_at,
                        payout_issued_by_id
                    FROM assistant_weekly_reviews
                    WHERE assistant_id = %s
                      AND week_start = %s
                    LIMIT 1
                    """,
                    (assistant_id, normalized_week_start),
                )
                previous_review = await cursor.fetchone() or {}
                previous_result = _canonical_weekly_result(previous_review.get("selected_result"))
                previous_static = str(previous_review.get("payout_static") or "").strip() or None
                previous_server_id = previous_review.get("payout_server_id")
                previous_issue_status = _canonical_weekly_payout_issue_status(previous_review.get("payout_issue_status"))
                payout_fields_changed = (
                    previous_result != normalized_result
                    or previous_review.get("payout_type") != payout_type
                    or previous_server_id != payout_server_id
                    or previous_static != normalized_static
                )
                payout_issue_reset = (
                    bool(previous_review)
                    and previous_issue_status == WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED
                    and payout_fields_changed
                )
                if payout_issue_reset:
                    previous_payout_preview = self._build_weekly_payout_preview(
                        assistant_role=assistant_role,
                        selected_result=previous_result,
                        payout_type=previous_review.get("payout_type"),
                        payout_server_id=int(previous_server_id) if previous_server_id is not None else None,
                        payout_static=previous_static,
                        payout_config=payout_config,
                    )
                    payout_issue_transition = {
                        "from_status": previous_issue_status,
                        "to_status": WEEKLY_PAYOUT_ISSUE_STATUS_PENDING,
                        "issued_at": previous_review.get("payout_issued_at"),
                        "issued_by_id": previous_review.get("payout_issued_by_id"),
                        "generated_payout_command": previous_payout_preview.get("command"),
                        "auto_reset": True,
                    }

                seen_dates: Set[date] = set()
                for override in day_overrides:
                    work_date = override.get("work_date")
                    manual_status = override.get("manual_status")
                    is_manual_override = bool(override.get("is_manual_override"))
                    if work_date is None:
                        raise ValueError("work_date is required")
                    if work_date in seen_dates:
                        raise ValueError("Повторяющиеся daily overrides недопустимы")
                    seen_dates.add(work_date)
                    if work_date < normalized_week_start or work_date > week_end:
                        raise ValueError("work_date должен находиться внутри выбранной недели")
                    if manual_status is not None and manual_status not in WEEKLY_MANUAL_STATUSES:
                        raise ValueError("Невалидный day status")

                    if not is_manual_override:
                        await cursor.execute(
                            """
                            DELETE FROM assistant_day_status_overrides
                            WHERE assistant_id = %s AND work_date = %s
                            """,
                            (assistant_id, work_date),
                        )
                    else:
                        stored_manual_status = manual_status or WEEKLY_MANUAL_STATUS_NONE
                        await cursor.execute(
                            """
                            INSERT INTO assistant_day_status_overrides (
                                assistant_id,
                                work_date,
                                manual_status,
                                updated_by_id
                            )
                            VALUES (%s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                manual_status = VALUES(manual_status),
                                updated_by_id = VALUES(updated_by_id),
                                updated_at = CURRENT_TIMESTAMP
                            """,
                            (assistant_id, work_date, stored_manual_status, actor_id),
                        )

                if (
                    normalized_result is None
                    and payout_type is None
                    and payout_server_id is None
                    and normalized_static is None
                ):
                    await cursor.execute(
                        """
                        DELETE FROM assistant_weekly_reviews
                        WHERE assistant_id = %s AND week_start = %s
                        """,
                        (assistant_id, normalized_week_start),
                    )
                else:
                    await cursor.execute(
                        """
                        INSERT INTO assistant_weekly_reviews (
                            assistant_id,
                            week_start,
                            selected_result,
                            payout_type,
                            payout_server_id,
                            payout_static,
                            payout_issue_status,
                            payout_issued_at,
                            payout_issued_by_id,
                            updated_by_id
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            selected_result = VALUES(selected_result),
                            payout_type = VALUES(payout_type),
                            payout_server_id = VALUES(payout_server_id),
                            payout_static = VALUES(payout_static),
                            payout_issue_status = VALUES(payout_issue_status),
                            payout_issued_at = VALUES(payout_issued_at),
                            payout_issued_by_id = VALUES(payout_issued_by_id),
                            updated_by_id = VALUES(updated_by_id),
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            assistant_id,
                            normalized_week_start,
                            normalized_result,
                            payout_type,
                            payout_server_id,
                            normalized_static,
                            WEEKLY_PAYOUT_ISSUE_STATUS_PENDING
                            if payout_issue_reset
                            else _canonical_weekly_payout_issue_status(previous_review.get("payout_issue_status")),
                            None if payout_issue_reset else previous_review.get("payout_issued_at"),
                            None if payout_issue_reset else previous_review.get("payout_issued_by_id"),
                            actor_id,
                        ),
                    )
                await conn.commit()

        detail = await self.get_assistant_weekly_admin_detail(
            assistant_id=assistant_id,
            week_start=normalized_week_start,
        )
        if detail is None:
            raise ValueError("Не удалось получить weekly detail после сохранения")
        if payout_issue_transition:
            detail["payout_issue_transition"] = payout_issue_transition
        return detail

    @db_retry()
    async def save_assistant_weekly_payout_issue_status(
        self,
        *,
        assistant_id: int,
        week_start: date,
        actor_id: Optional[int],
        payout_issue_status: str,
    ) -> Dict[str, Any]:
        normalized_week_start = _week_start_msk(week_start)
        week_end = normalized_week_start + timedelta(days=6)
        normalized_status = _canonical_weekly_payout_issue_status(payout_issue_status)
        payout_issue_transition = None

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT pr_id, role
                    FROM assistants
                    WHERE pr_id = %s
                      AND COALESCE(appointed_at, added_at, CURRENT_TIMESTAMP) < %s
                      AND (dismissed_at IS NULL OR dismissed_at >= %s)
                    LIMIT 1
                    """,
                    (
                        assistant_id,
                        datetime.combine(week_end + timedelta(days=1), datetime.min.time()),
                        datetime.combine(normalized_week_start, datetime.min.time()),
                    ),
                )
                assistant = await cursor.fetchone()
                if not assistant:
                    raise ValueError("Ассистент не найден")

                payout_config = await self._get_weekly_payout_config_locked(cursor)
                await cursor.execute(
                    """
                    SELECT
                        selected_result,
                        payout_type,
                        payout_server_id,
                        payout_static,
                        payout_issue_status,
                        payout_issued_at,
                        payout_issued_by_id
                    FROM assistant_weekly_reviews
                    WHERE assistant_id = %s
                      AND week_start = %s
                    LIMIT 1
                    """,
                    (assistant_id, normalized_week_start),
                )
                review = await cursor.fetchone() or {}
                current_status = _canonical_weekly_payout_issue_status(review.get("payout_issue_status"))
                payout_server_id = review.get("payout_server_id")

                if not review:
                    if normalized_status == WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED:
                        raise ValueError("Нельзя отметить выдачу без сохранённой weekly review")
                    detail = await self.get_assistant_weekly_admin_detail(
                        assistant_id=assistant_id,
                        week_start=normalized_week_start,
                    )
                    if detail is None:
                        raise ValueError("Не удалось получить weekly detail")
                    return detail

                selected_result = _canonical_weekly_result(review.get("selected_result"))
                normalized_static = str(review.get("payout_static") or "").strip() or None
                payout_preview = self._build_weekly_payout_preview(
                    assistant_role=assistant.get("role"),
                    selected_result=selected_result,
                    payout_type=review.get("payout_type"),
                    payout_server_id=int(payout_server_id) if payout_server_id is not None else None,
                    payout_static=normalized_static,
                    payout_config=payout_config,
                )

                if normalized_status == current_status:
                    detail = await self.get_assistant_weekly_admin_detail(
                        assistant_id=assistant_id,
                        week_start=normalized_week_start,
                    )
                    if detail is None:
                        raise ValueError("Не удалось получить weekly detail")
                    return detail

                if normalized_status == WEEKLY_PAYOUT_ISSUE_STATUS_ISSUED and not payout_preview.get("command_available"):
                    raise ValueError("Команда недоступна для выдачи")

                await cursor.execute(
                    """
                    UPDATE assistant_weekly_reviews
                    SET payout_issue_status = %s,
                        payout_issued_at = CASE
                            WHEN %s = 'issued' THEN CURRENT_TIMESTAMP
                            ELSE NULL
                        END,
                        payout_issued_by_id = CASE
                            WHEN %s = 'issued' THEN %s
                            ELSE NULL
                        END,
                        updated_by_id = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE assistant_id = %s
                      AND week_start = %s
                    """,
                    (
                        normalized_status,
                        normalized_status,
                        normalized_status,
                        actor_id,
                        actor_id,
                        assistant_id,
                        normalized_week_start,
                    ),
                )
                await conn.commit()
                payout_issue_transition = {
                    "from_status": current_status,
                    "to_status": normalized_status,
                    "issued_at": review.get("payout_issued_at"),
                    "issued_by_id": review.get("payout_issued_by_id"),
                    "generated_payout_command": payout_preview.get("command"),
                    "auto_reset": False,
                }

        detail = await self.get_assistant_weekly_admin_detail(
            assistant_id=assistant_id,
            week_start=normalized_week_start,
        )
        if detail is None:
            raise ValueError("Не удалось получить weekly detail")
        detail["payout_issue_transition"] = payout_issue_transition
        return detail
