from __future__ import annotations

from .core import (
    Any,
    CURRENT_SANCTION_POLICY_MONTH,
    Dict,
    FIXED_SIZE_SANCTION_KINDS,
    List,
    MSK,
    Optional,
    SANCTIONS_GLOBAL_LOCK_NAME,
    SANCTIONS_NIGHTLY_STALE_SECONDS,
    WARNING_SANCTION_KINDS,
    _date_only,
    _month_start,
    _msk_now,
    _msk_today,
    _sum_numeric,
    date,
    datetime,
    db_retry,
    json,
    timedelta,
)


class SanctionsRuntimeMixin:
    @staticmethod
    def _current_msk_date() -> date:
        return datetime.now(MSK).date()

    @staticmethod
    def _normalize_runtime_sanction(
        *,
        kind: str,
        amount: Optional[float],
        auto_relief_date: Optional[date],
    ) -> tuple[float, Optional[date]]:
        safe_kind = str(kind)
        if safe_kind in FIXED_SIZE_SANCTION_KINDS:
            normalized_amount = 1.0
        else:
            if amount is None or float(amount) <= 0:
                raise ValueError("Для выбранной санкции требуется положительный размер")
            normalized_amount = round(float(amount), 4)

        normalized_auto_relief_date = auto_relief_date if safe_kind in WARNING_SANCTION_KINDS else None
        if safe_kind in WARNING_SANCTION_KINDS and normalized_auto_relief_date is None:
            raise ValueError("Для устного и строгого требуется дата автоматического снятия")
        return normalized_amount, normalized_auto_relief_date

    @staticmethod
    def _nightly_run_context_for_basis_date(basis_date: date) -> Dict[str, Any]:
        processing_date = basis_date + timedelta(days=1)
        run_started_at = datetime.combine(processing_date, datetime.min.time())
        return {
            "basis_date": basis_date,
            "processing_date": processing_date,
            "run_started_at": run_started_at,
        }

    async def _get_day_spec_metrics_map_locked(
        self,
        cursor,
        *,
        assistant_ids: List[int],
        work_date: date,
    ) -> Dict[int, Dict[str, Any]]:
        if not assistant_ids:
            return {}

        day_start = datetime.combine(work_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        placeholders = ", ".join(["%s"] * len(assistant_ids))
        await cursor.execute(
            f"""
            SELECT
                ss.pr_id AS assistant_id,
                COALESCE(
                    SUM(
                        GREATEST(
                            0,
                            TIMESTAMPDIFF(
                                SECOND,
                                GREATEST(ss.started_at, %s),
                                LEAST(COALESCE(ss.ended_at, %s), %s)
                            )
                        )
                    ),
                    0
                ) AS spec_seconds_on_day,
                ROUND(
                    COALESCE(
                        SUM(
                            (GREATEST(
                                0,
                                TIMESTAMPDIFF(
                                    SECOND,
                                    GREATEST(ss.started_at, %s),
                                    LEAST(COALESCE(ss.ended_at, %s), %s)
                                )
                            ) / 3600.0) * ss.applied_hourly_rate
                        ),
                        0
                    ),
                    4
                ) AS spec_points_auto
            FROM spec_sessions ss
            LEFT JOIN events e
              ON ss.target_type = 'event'
             AND e.id = ss.target_id
            WHERE ss.pr_id IN ({placeholders})
              AND ss.deleted_at IS NULL
              AND ss.started_at < %s
              AND COALESCE(ss.ended_at, %s) > %s
              AND (ss.target_type <> 'event' OR e.approval_status = 'approved')
            GROUP BY ss.pr_id
            """,
            (
                day_start,
                day_end,
                day_end,
                day_start,
                day_end,
                day_end,
                *assistant_ids,
                day_end,
                day_end,
                day_start,
            ),
        )
        rows = await cursor.fetchall() or []
        result: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            assistant_id_value = int(row.get("assistant_id") or 0)
            seconds = int(row.get("spec_seconds_on_day") or 0)
            result[assistant_id_value] = {
                "spec_seconds_on_day": seconds,
                "spec_hours_on_day": round(seconds / 3600.0, 4),
                "spec_points_auto": round(float(row.get("spec_points_auto") or 0), 4),
            }
        return result

    async def _get_streak_days_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        work_date: date,
        min_hours: float,
        limit_days: int = 60,
    ) -> int:
        streak = 0
        cursor_date = work_date
        for _ in range(limit_days):
            manual_status_row = await self._get_day_manual_status_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=cursor_date,
            )
            if manual_status_row.get("is_leave_day"):
                break
            metrics = await self._get_day_spec_metrics_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=cursor_date,
            )
            if float(metrics.get("spec_hours_on_day") or 0) + 1e-9 < float(min_hours):
                break
            streak += 1
            cursor_date = cursor_date - timedelta(days=1)
        return streak

    async def _get_assistant_day_status_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        work_date: date,
    ) -> Dict[str, Any]:
        policy = await self._ensure_monthly_policy_row(cursor, self._month_start_for(work_date))
        metrics = await self._get_day_spec_metrics_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
        )
        manual_status_row = await self._get_day_manual_status_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
        )
        manual_status = manual_status_row.get("manual_status")
        is_leave_day = bool(manual_status_row.get("is_leave_day"))

        await cursor.execute(
            """
            SELECT delta_points
            FROM assistant_day_point_adjustments
            WHERE assistant_id = %s AND work_date = %s
            """,
            (assistant_id, work_date),
        )
        adjustment_row = await cursor.fetchone() or {}

        await cursor.execute(
            """
            SELECT mchat_count
            FROM assistant_day_mchat
            WHERE assistant_id = %s AND work_date = %s
            """,
            (assistant_id, work_date),
        )
        mchat_row = await cursor.fetchone() or {}

        await cursor.execute(
            """
            SELECT COUNT(*) AS complaints_count
            FROM complaints
            WHERE assistant_id = %s
              AND status IN ('issued', 'completed')
              AND DATE(COALESCE(issued_at, completed_at)) = %s
            """,
            (assistant_id, work_date),
        )
        complaints_row = await cursor.fetchone() or {}

        streak_check = await self._get_streak_days_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
            min_hours=float(policy.get("check_relief_hours_per_day") or 4),
        )
        streak_point = await self._get_streak_days_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
            min_hours=float(policy.get("point_relief_hours_per_day") or 5),
        )
        streak_percent = await self._get_streak_days_locked(
            cursor,
            assistant_id=assistant_id,
            work_date=work_date,
            min_hours=float(policy.get("percent_relief_hours_per_day") or 6),
        )

        spec_hours = float(metrics.get("spec_hours_on_day") or 0)
        return {
            "assistant_id": assistant_id,
            "work_date": work_date,
            "manual_status": manual_status,
            "is_leave_day": is_leave_day,
            "spec_seconds_on_day": int(metrics.get("spec_seconds_on_day") or 0),
            "spec_hours_on_day": round(spec_hours, 4),
            "spec_points_auto": round(float(metrics.get("spec_points_auto") or 0), 4),
            "manual_points_delta": round(float(adjustment_row.get("delta_points") or 0), 4),
            "mchat_count": int(mchat_row.get("mchat_count") or 0),
            "complaints_count": int(complaints_row.get("complaints_count") or 0),
            "check_immunity": spec_hours + 1e-9 >= float(policy.get("check_immunity_hours_per_day") or 4),
            "point_immunity": spec_hours + 1e-9 >= float(policy.get("point_immunity_hours_per_day") or 5),
            "percent_immunity": spec_hours + 1e-9 >= float(policy.get("percent_immunity_hours_per_day") or 6),
            "streak_check_days": streak_check,
            "streak_point_days": streak_point,
            "streak_percent_days": streak_percent,
        }

    async def _insert_sanction_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        kind: str,
        amount_total: float,
        auto_relief_date: Optional[date] = None,
        source_type: str,
        issued_at: Optional[datetime] = None,
        basis_date: Optional[date] = None,
        source_batch_id: Optional[int] = None,
        policy_month: Optional[date] = None,
        cycle_no: Optional[int] = None,
    ) -> int:
        normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
            kind=kind,
            amount=amount_total,
            auto_relief_date=auto_relief_date,
        )
        if issued_at is None:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (
                    assistant_id,
                    kind,
                    amount_total,
                    auto_relief_date,
                    issued_at,
                    source_type,
                    operation_id,
                    basis_date,
                    settings_month,
                    check_rule_hit_no
                )
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s)
                """,
                (
                    assistant_id,
                    kind,
                    normalized_amount,
                    normalized_auto_relief_date,
                    source_type,
                    source_batch_id,
                    basis_date,
                    policy_month,
                    cycle_no,
                ),
            )
        else:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (
                    assistant_id,
                    kind,
                    amount_total,
                    auto_relief_date,
                    issued_at,
                    source_type,
                    operation_id,
                    basis_date,
                    settings_month,
                    check_rule_hit_no
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    assistant_id,
                    kind,
                    normalized_amount,
                    normalized_auto_relief_date,
                    issued_at,
                    source_type,
                    source_batch_id,
                    basis_date,
                    policy_month,
                    cycle_no,
                ),
            )
        return int(cursor.lastrowid)

    async def _apply_check_cycle_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        basis_date: date,
        source_batch_id: Optional[int] = None,
        run_timestamp: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        month_start = self._month_start_for(basis_date)
        policy = await self._ensure_monthly_policy_row(cursor, month_start)
        cycle_size = int(policy.get("check_cycle_size") or 5)

        await cursor.execute(
            """
            SELECT
                sb.sanction_id,
                sb.active_amount
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.assistant_id = %s
              AND s.kind = 'check'
              AND sb.active_amount > 0
              AND s.basis_date >= %s
              AND s.basis_date < DATE_ADD(%s, INTERVAL 1 MONTH)
            ORDER BY s.basis_date ASC, s.issued_at ASC, s.id ASC
            """,
            (assistant_id, month_start, month_start),
        )
        open_checks = await cursor.fetchall() or []
        total_open_checks = sum(float(row.get("active_amount") or 0) for row in open_checks)
        if total_open_checks + 1e-9 < cycle_size:
            return None

        await cursor.execute(
            """
            SELECT COALESCE(MAX(check_rule_hit_no), 0) AS max_cycle
            FROM assistant_sanctions
            WHERE assistant_id = %s
              AND source_type = 'check_cycle'
              AND settings_month = %s
            """,
            (assistant_id, month_start),
        )
        cycle_row = await cursor.fetchone() or {}
        cycle_no = int(cycle_row.get("max_cycle") or 0) + 1

        await cursor.execute(
            """
            SELECT penalty_kind AS sanction_kind, penalty_amount AS sanction_amount
            FROM monthly_check_rules
            WHERE month_start = %s
              AND %s >= range_start
              AND (range_end IS NULL OR %s <= range_end)
            ORDER BY range_start DESC, COALESCE(range_end, 4294967295) DESC, id DESC
            LIMIT 1
            """,
            (month_start, cycle_no, cycle_no),
        )
        rule = await cursor.fetchone()
        if not rule:
            return None

        derived_sanction_id = await self._insert_sanction_locked(
            cursor,
            assistant_id=assistant_id,
            kind=str(rule.get("sanction_kind")),
            amount_total=float(rule.get("sanction_amount") or 0),
            source_type="check_cycle",
            issued_at=run_timestamp,
            basis_date=basis_date,
            source_batch_id=source_batch_id,
            policy_month=month_start,
            cycle_no=cycle_no,
        )

        remaining_to_consume = float(cycle_size)
        consumed_check_ids: List[int] = []
        for row in open_checks:
            if remaining_to_consume <= 0:
                break
            available = float(row.get("active_amount") or 0)
            if available <= 0:
                continue
            relief_amount = min(available, remaining_to_consume)
            if run_timestamp is None:
                await cursor.execute(
                    """
                    INSERT INTO assistant_sanction_reliefs (
                        sanction_id, amount, relieved_at, basis_date, relief_type
                    )
                    VALUES (%s, %s, CURRENT_TIMESTAMP, %s, 'cycle_reset')
                    """,
                    (row["sanction_id"], relief_amount, basis_date),
                )
            else:
                await cursor.execute(
                    """
                    INSERT INTO assistant_sanction_reliefs (
                        sanction_id, amount, relieved_at, basis_date, relief_type
                    )
                    VALUES (%s, %s, %s, %s, 'cycle_reset')
                    """,
                    (row["sanction_id"], relief_amount, run_timestamp, basis_date),
                )
            remaining_to_consume -= relief_amount
            consumed_check_ids.append(int(row["sanction_id"]))

        return {
            "derived_sanction_id": derived_sanction_id,
            "cycle_no": cycle_no,
            "rule": dict(rule),
            "consumed_check_ids": consumed_check_ids,
        }

    async def _active_sanction_candidate_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        kind: str,
        run_started_at: datetime,
        basis_date: date,
    ) -> Optional[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT sb.sanction_id, sb.active_amount
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.assistant_id = %s
              AND s.kind = %s
              AND s.issued_at < %s
              AND sb.active_amount > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM assistant_sanction_reliefs sr
                  WHERE sr.sanction_id = s.id
                    AND sr.relief_type = 'default'
                    AND sr.basis_date = %s
              )
            ORDER BY s.issued_at ASC, s.id ASC
            """,
            (assistant_id, kind, run_started_at, basis_date),
        )
        candidates = await cursor.fetchall() or []
        for candidate in candidates:
            workoff_state = await self._get_sanction_workoff_state_locked(
                cursor,
                sanction_id=int(candidate["sanction_id"]),
                assistant_id=assistant_id,
                evaluation_cutoff=basis_date,
            )
            effective_period_end = workoff_state.get("effective_period_end")
            if workoff_state.get("has_workoff") and effective_period_end is not None and effective_period_end > basis_date:
                continue
            return candidate
        return None

    async def _get_sanction_workoff_items_locked(
        self,
        cursor,
        *,
        sanction_id: int,
    ) -> List[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT id, sanction_id, metric, multiplier, period_start, period_end, target_amount, created_at
            FROM assistant_sanction_workoffs
            WHERE sanction_id = %s
            ORDER BY id ASC
            """,
            (sanction_id,),
        )
        return await cursor.fetchall() or []

    @staticmethod
    def _build_sanction_workoff_summary(workoff_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not workoff_items:
            return {
                "workoff_period_start": None,
                "workoff_period_end": None,
                "workoff_target_spec": None,
                "workoff_target_complaints": None,
                "workoff_target_mchat": None,
            }
        period_start = min(item["period_start"] for item in workoff_items)
        period_end = max(item["period_end"] for item in workoff_items)
        total_spec = sum(float(item.get("target_amount") or 0) for item in workoff_items if item.get("metric") == "spec")
        total_complaints = sum(float(item.get("target_amount") or 0) for item in workoff_items if item.get("metric") == "complaints")
        total_mchat = sum(float(item.get("target_amount") or 0) for item in workoff_items if item.get("metric") == "mchat")
        return {
            "workoff_period_start": period_start,
            "workoff_period_end": period_end,
            "workoff_target_spec": round(total_spec, 4) if total_spec else None,
            "workoff_target_complaints": int(round(total_complaints)) if total_complaints else None,
            "workoff_target_mchat": int(round(total_mchat)) if total_mchat else None,
        }

    async def _get_workoff_progress_items_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        workoff_items: List[Dict[str, Any]],
        evaluation_cutoff: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        progress_items: List[Dict[str, Any]] = []
        for item in workoff_items:
            progress_items.append(
                await self._evaluate_workoff_item_progress_locked(
                    cursor,
                    assistant_id=assistant_id,
                    item=item,
                    evaluation_cutoff=evaluation_cutoff,
                )
            )
        return progress_items

    async def _evaluate_workoff_item_progress_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        item: Dict[str, Any],
        evaluation_cutoff: Optional[date] = None,
    ) -> Dict[str, Any]:
        metric = str(item["metric"])
        period_start = item["period_start"]
        period_end = item["period_end"]
        cutoff = evaluation_cutoff or self._current_msk_date()
        required_work_days = (period_end - period_start).days + 1
        counted_projected_days = 0
        counted_work_days = 0
        uo_days_count = 0
        amount_done = 0.0
        target_amount = 0.0
        failed = False
        days: List[Dict[str, Any]] = []
        cursor_day = period_start
        effective_period_end = period_end

        while counted_projected_days < required_work_days:
            manual_status_row = await self._get_day_manual_status_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=cursor_day,
            )
            manual_status = manual_status_row.get("manual_status")
            is_leave_day = bool(manual_status_row.get("is_leave_day"))
            actual_amount: Optional[float] = None
            required_amount: Optional[float] = None

            if is_leave_day:
                uo_days_count += 1
                day_status = "leave_skipped"
                counts_for_workoff = False
            else:
                counts_for_workoff = True
                required_amount = await self._daily_norm_amount_locked(
                    cursor,
                    metric=metric,
                    work_date=cursor_day,
                    multiplier=float(item.get("multiplier") or 0),
                )
                target_amount += float(required_amount or 0)
                counted_projected_days += 1
                if cursor_day > cutoff:
                    day_status = "pending"
                else:
                    actual_amount = await self._day_metric_amount_locked(
                        cursor,
                        assistant_id=assistant_id,
                        metric=metric,
                        work_date=cursor_day,
                    )
                    counted_work_days += 1
                    amount_done += float(actual_amount or 0)
                    if float(actual_amount or 0) + 1e-9 >= float(required_amount or 0):
                        day_status = "completed"
                    else:
                        day_status = "failed"
                        failed = True

            days.append(
                {
                    "date": cursor_day,
                    "manual_status": manual_status,
                    "counts_for_workoff": counts_for_workoff,
                    "required_amount": round(float(required_amount), 4)
                    if required_amount is not None and metric == "spec"
                    else (int(round(required_amount)) if required_amount is not None else None),
                    "actual_amount": round(float(actual_amount), 4)
                    if actual_amount is not None and metric == "spec"
                    else (int(round(actual_amount)) if actual_amount is not None else None),
                    "day_status": day_status,
                }
            )
            effective_period_end = cursor_day
            cursor_day += timedelta(days=1)

        if failed:
            status = "failed"
        elif cutoff < effective_period_end:
            status = "pending"
        else:
            status = "completed"

        normalized_target_amount = round(target_amount, 4) if metric == "spec" else int(round(target_amount))
        normalized_amount_done = round(amount_done, 4) if metric == "spec" else int(round(amount_done))
        remaining_amount = max(float(normalized_target_amount) - float(normalized_amount_done), 0.0)
        normalized_remaining_amount = round(remaining_amount, 4) if metric == "spec" else int(round(remaining_amount))

        return {
            **item,
            "required_work_days": required_work_days,
            "counted_work_days": counted_work_days,
            "effective_period_end": effective_period_end,
            "uo_days_count": uo_days_count,
            "status": status,
            "days": days,
            "target_amount": normalized_target_amount,
            "amount_done": normalized_amount_done,
            "remaining_amount": normalized_remaining_amount,
            "is_completed": status == "completed",
        }

    @staticmethod
    def _build_workoff_progress_summary(progress_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "has_workoff": bool(progress_items),
            "total_items": len(progress_items),
            "completed_items": sum(1 for item in progress_items if str(item.get("status") or "") == "completed"),
            "items": progress_items,
        }

    async def _day_metric_amount_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        metric: str,
        work_date: date,
    ) -> float:
        if metric == "spec":
            metrics = await self._get_day_spec_metrics_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=work_date,
            )
            return round(float(metrics.get("spec_hours_on_day") or 0), 4)

        if metric == "complaints":
            await cursor.execute(
                """
                SELECT COUNT(*) AS amount_done
                FROM complaints
                WHERE assistant_id = %s
                  AND status IN ('issued', 'completed')
                  AND DATE(COALESCE(issued_at, completed_at)) = %s
                """,
                (assistant_id, work_date),
            )
            row = await cursor.fetchone() or {}
            return float(int(row.get("amount_done") or 0))

        await cursor.execute(
            """
            SELECT mchat_count
            FROM assistant_day_mchat
            WHERE assistant_id = %s
              AND work_date = %s
            LIMIT 1
            """,
            (assistant_id, work_date),
        )
        row = await cursor.fetchone() or {}
        return float(int(row.get("mchat_count") or 0))

    async def _replace_batch_workoff_items_locked(
        self,
        cursor,
        *,
        batch_id: int,
        workoff_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized = self._normalize_workoff_items(workoff_items)
        await cursor.execute(
            "DELETE FROM sanction_operation_workoffs WHERE operation_id = %s",
            (batch_id,),
        )
        for item in normalized:
            await cursor.execute(
                """
                INSERT INTO sanction_operation_workoffs (
                    operation_id, metric, multiplier, period_start, period_end
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    batch_id,
                    item["metric"],
                    item["multiplier"],
                    item["period_start"],
                    item["period_end"],
                ),
            )
        return normalized

    async def _get_batch_workoff_items_locked(
        self,
        cursor,
        *,
        batch_id: int,
    ) -> List[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT id, operation_id AS batch_id, metric, multiplier, period_start, period_end, created_at
            FROM sanction_operation_workoffs
            WHERE operation_id = %s
            ORDER BY id ASC
            """,
            (batch_id,),
        )
        return await cursor.fetchall() or []

    async def _compute_workoff_item_target_amount_locked(
        self,
        cursor,
        *,
        metric: str,
        multiplier: float,
        period_start: date,
        period_end: date,
    ) -> float:
        target = 0.0
        cursor_day = period_start
        while cursor_day <= period_end:
            target += await self._daily_norm_amount_locked(
                cursor,
                metric=metric,
                work_date=cursor_day,
                multiplier=multiplier,
            )
            cursor_day += timedelta(days=1)
        if metric == "spec":
            return round(target, 4)
        return float(int(round(target)))

    async def _daily_norm_amount_locked(
        self,
        cursor,
        *,
        metric: str,
        work_date: date,
        multiplier: float,
    ) -> float:
        policy = await self._ensure_monthly_policy_row(cursor, self._month_start_for(work_date))
        field_name = {
            "spec": "daily_norm_spec",
            "complaints": "daily_norm_complaints",
            "mchat": "daily_norm_mchat",
        }[metric]
        amount = float(policy.get(field_name) or 0) * float(multiplier)
        if metric == "spec":
            return round(amount, 4)
        return float(int(round(amount)))

    @staticmethod
    def _normalize_workoff_items(workoff_items: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for raw_item in workoff_items or []:
            metric = str(raw_item.get("metric") or "").strip()
            if metric not in {"spec", "complaints", "mchat"}:
                raise ValueError("Unsupported workoff metric")
            multiplier = float(raw_item.get("multiplier") or 0)
            if multiplier <= 0:
                raise ValueError("Workoff multiplier must be greater than 0")
            period_start = raw_item.get("period_start")
            period_end = raw_item.get("period_end")
            if not isinstance(period_start, date) or not isinstance(period_end, date):
                raise ValueError("Workoff period must include valid start and end dates")
            if period_end < period_start:
                raise ValueError("Workoff period_end must be greater than or equal to period_start")
            normalized.append(
                {
                    "metric": metric,
                    "multiplier": multiplier,
                    "period_start": period_start,
                    "period_end": period_end,
                }
            )
        return normalized

    async def _create_sanction_workoff_items_locked(
        self,
        cursor,
        *,
        sanction_id: int,
        workoff_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized = self._normalize_workoff_items(workoff_items)
        created: List[Dict[str, Any]] = []
        for item in normalized:
            target_amount = await self._compute_workoff_item_target_amount_locked(
                cursor,
                metric=item["metric"],
                multiplier=float(item["multiplier"]),
                period_start=item["period_start"],
                period_end=item["period_end"],
            )
            await cursor.execute(
                """
                INSERT INTO assistant_sanction_workoffs (
                    sanction_id, metric, multiplier, period_start, period_end, target_amount
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    sanction_id,
                    item["metric"],
                    item["multiplier"],
                    item["period_start"],
                    item["period_end"],
                    target_amount,
                ),
            )
            created.append(
                {
                    "id": int(cursor.lastrowid),
                    "sanction_id": sanction_id,
                    "metric": item["metric"],
                    "multiplier": float(item["multiplier"]),
                    "period_start": item["period_start"],
                    "period_end": item["period_end"],
                    "target_amount": target_amount,
                }
            )
        return created

    async def _sync_sanction_workoff_summary_locked(
        self,
        cursor,
        *,
        sanction_id: int,
        workoff_items: List[Dict[str, Any]],
    ) -> None:
        return None

    async def _get_sanction_workoff_state_locked(
        self,
        cursor,
        *,
        sanction_id: int,
        assistant_id: int,
        evaluation_cutoff: Optional[date],
    ) -> Dict[str, Any]:
        workoff_items = await self._get_sanction_workoff_items_locked(
            cursor,
            sanction_id=sanction_id,
        )
        if not workoff_items:
            return {
                "has_workoff": False,
                "items": [],
                "effective_period_end": None,
                "all_completed": False,
                "any_failed": False,
            }

        progress_items = await self._get_workoff_progress_items_locked(
            cursor,
            assistant_id=assistant_id,
            workoff_items=workoff_items,
            evaluation_cutoff=evaluation_cutoff,
        )
        effective_period_end = max(
            (item.get("effective_period_end") for item in progress_items if item.get("effective_period_end") is not None),
            default=None,
        )
        return {
            "has_workoff": True,
            "items": progress_items,
            "effective_period_end": effective_period_end,
            "all_completed": bool(progress_items)
            and all(str(item.get("status") or "") == "completed" for item in progress_items),
            "any_failed": any(str(item.get("status") or "") == "failed" for item in progress_items),
        }

    async def _apply_custom_workoff_relief_locked(
        self,
        cursor,
        *,
        basis_date: date,
        run_started_at: datetime,
        assistant_filter: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        await cursor.execute(
            """
            SELECT
                sb.sanction_id,
                sb.assistant_id,
                sb.kind,
                sb.active_amount
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.issued_at < %s
              AND sb.active_amount > 0
              AND EXISTS (
                  SELECT 1
                  FROM assistant_sanction_workoffs sw
                  WHERE sw.sanction_id = s.id
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM assistant_sanction_reliefs sr
                  WHERE sr.sanction_id = s.id
                    AND sr.relief_type = 'custom_workoff'
              )
            ORDER BY s.issued_at ASC, s.id ASC
            """,
            (run_started_at,),
        )
        rows = await cursor.fetchall() or []
        relieved: List[Dict[str, Any]] = []
        for row in rows:
            assistant_id = int(row["assistant_id"])
            if assistant_filter is not None and assistant_id not in assistant_filter:
                continue
            workoff_state = await self._get_sanction_workoff_state_locked(
                cursor,
                sanction_id=int(row["sanction_id"]),
                assistant_id=assistant_id,
                evaluation_cutoff=basis_date,
            )
            effective_period_end = workoff_state.get("effective_period_end")
            if effective_period_end is None or effective_period_end > basis_date:
                continue
            if not workoff_state.get("all_completed"):
                continue
            amount = round(float(row.get("active_amount") or 0), 4)
            if amount <= 0:
                continue
            await cursor.execute(
                """
                INSERT INTO assistant_sanction_reliefs (
                    sanction_id, amount, relieved_at, basis_date, relief_type
                )
                VALUES (%s, %s, %s, %s, 'custom_workoff')
                """,
                (row["sanction_id"], amount, run_started_at, basis_date),
            )
            relieved.append(
                {
                    "assistant_id": assistant_id,
                    "sanction_id": int(row["sanction_id"]),
                    "kind": str(row["kind"]),
                    "amount": amount,
                    "effective_period_end": effective_period_end,
                }
            )
        return {"relieved": relieved}

    async def _apply_warning_auto_expiry_locked(
        self,
        cursor,
        *,
        current_date: date,
        run_started_at: datetime,
        assistant_filter: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        await cursor.execute(
            """
            SELECT
                sb.sanction_id,
                sb.assistant_id,
                sb.kind,
                sb.active_amount
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.kind IN ('oral', 'strict')
              AND s.auto_relief_date IS NOT NULL
              AND s.auto_relief_date <= %s
              AND sb.active_amount > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM assistant_sanction_reliefs sr
                  WHERE sr.sanction_id = s.id
                    AND sr.relief_type = 'auto_expire'
              )
            ORDER BY s.auto_relief_date ASC, s.issued_at ASC, s.id ASC
            """,
            (current_date,),
        )
        rows = await cursor.fetchall() or []
        expired: List[Dict[str, Any]] = []
        for row in rows:
            assistant_id = int(row["assistant_id"])
            if assistant_filter is not None and assistant_id not in assistant_filter:
                continue
            amount = round(float(row.get("active_amount") or 0), 4)
            if amount <= 0:
                continue
            await cursor.execute(
                """
                INSERT INTO assistant_sanction_reliefs (
                    sanction_id, amount, relieved_at, basis_date, relief_type
                )
                VALUES (%s, %s, %s, %s, 'auto_expire')
                """,
                (row["sanction_id"], amount, run_started_at, current_date),
            )
            expired.append(
                {
                    "assistant_id": assistant_id,
                    "sanction_id": int(row["sanction_id"]),
                    "kind": str(row["kind"]),
                    "amount": amount,
                }
            )
        return {"relieved": expired}

    async def _apply_default_auto_relief_locked(
        self,
        cursor,
        *,
        basis_date: date,
        run_started_at: datetime,
        assistant_filter: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        month_start = self._month_start_for(basis_date)
        policy = await self._ensure_monthly_policy_row(cursor, month_start)

        await cursor.execute(
            """
            SELECT DISTINCT s.assistant_id
            FROM assistant_sanctions s
            JOIN sanction_balances sb ON sb.sanction_id = s.id
            WHERE s.issued_at < %s
              AND sb.active_amount > 0
            """,
            (run_started_at,),
        )
        assistant_rows = await cursor.fetchall() or []

        relieved: List[Dict[str, Any]] = []
        for row in assistant_rows:
            assistant_id = int(row["assistant_id"])
            if assistant_filter is not None and assistant_id not in assistant_filter:
                continue
            day_status = await self._get_assistant_day_status_locked(
                cursor,
                assistant_id=assistant_id,
                work_date=basis_date,
            )

            if int(day_status.get("streak_check_days") or 0) >= int(policy.get("check_relief_min_streak_days") or 2):
                candidate = await self._active_sanction_candidate_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind="check",
                    run_started_at=run_started_at,
                    basis_date=basis_date,
                )
                if candidate and float(candidate.get("active_amount") or 0) > 0:
                    amount = min(1.0, float(candidate.get("active_amount") or 0))
                    await cursor.execute(
                        """
                        INSERT INTO assistant_sanction_reliefs (
                            sanction_id, amount, relieved_at, basis_date, relief_type
                        )
                        VALUES (%s, %s, %s, %s, 'default')
                        """,
                        (candidate["sanction_id"], amount, run_started_at, basis_date),
                    )
                    relieved.append(
                        {
                            "assistant_id": assistant_id,
                            "kind": "check",
                            "sanction_id": int(candidate["sanction_id"]),
                            "amount": amount,
                        }
                    )

            point_candidate = None
            if int(day_status.get("streak_point_days") or 0) >= int(policy.get("point_relief_min_streak_days") or 2):
                point_candidate = await self._active_sanction_candidate_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind="point",
                    run_started_at=run_started_at,
                    basis_date=basis_date,
                )
                if point_candidate and float(point_candidate.get("active_amount") or 0) > 0:
                    amount = min(1.0, float(point_candidate.get("active_amount") or 0))
                    await cursor.execute(
                        """
                        INSERT INTO assistant_sanction_reliefs (
                            sanction_id, amount, relieved_at, basis_date, relief_type
                        )
                        VALUES (%s, %s, %s, %s, 'default')
                        """,
                        (point_candidate["sanction_id"], amount, run_started_at, basis_date),
                    )
                    relieved.append(
                        {
                            "assistant_id": assistant_id,
                            "kind": "point",
                            "sanction_id": int(point_candidate["sanction_id"]),
                            "amount": amount,
                        }
                    )
                    continue

            if int(day_status.get("streak_percent_days") or 0) >= int(policy.get("percent_relief_min_streak_days") or 2):
                percent_candidate = await self._active_sanction_candidate_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind="percent",
                    run_started_at=run_started_at,
                    basis_date=basis_date,
                )
                if percent_candidate and float(percent_candidate.get("active_amount") or 0) > 0:
                    amount = min(
                        float(policy.get("percent_relief_step_amount") or 3),
                        float(percent_candidate.get("active_amount") or 0),
                    )
                    await cursor.execute(
                        """
                        INSERT INTO assistant_sanction_reliefs (
                            sanction_id, amount, relieved_at, basis_date, relief_type
                        )
                        VALUES (%s, %s, %s, %s, 'default')
                        """,
                        (percent_candidate["sanction_id"], amount, run_started_at, basis_date),
                    )
                    relieved.append(
                        {
                            "assistant_id": assistant_id,
                            "kind": "percent",
                            "sanction_id": int(percent_candidate["sanction_id"]),
                            "amount": amount,
                        }
                    )

        return {"relieved": relieved}

    async def _apply_month_end_check_reset_locked(
        self,
        cursor,
        *,
        basis_date: date,
        run_started_at: datetime,
        assistant_filter: Optional[Set[int]] = None,
    ) -> Dict[str, Any]:
        next_day = basis_date + timedelta(days=1)
        if next_day.month == basis_date.month:
            return {"reset_count": 0}

        month_start = self._month_start_for(basis_date)
        await cursor.execute(
            """
            SELECT sb.sanction_id, sb.active_amount, s.assistant_id
            FROM sanction_balances sb
            JOIN assistant_sanctions s ON s.id = sb.sanction_id
            WHERE s.kind = 'check'
              AND s.issued_at < %s
              AND s.basis_date >= %s
              AND s.basis_date < DATE_ADD(%s, INTERVAL 1 MONTH)
              AND sb.active_amount > 0
            """,
            (run_started_at, month_start, month_start),
        )
        rows = await cursor.fetchall() or []
        if assistant_filter is not None:
            rows = [row for row in rows if int(row.get("assistant_id") or 0) in assistant_filter]
        for row in rows:
            await cursor.execute(
                """
                INSERT INTO assistant_sanction_reliefs (
                    sanction_id, amount, relieved_at, basis_date, relief_type
                )
                VALUES (%s, %s, %s, %s, 'month_reset')
                """,
                (row["sanction_id"], float(row["active_amount"] or 0), run_started_at, basis_date),
            )
        return {"reset_count": len(rows)}

    @db_retry()
    async def get_assistant_sanctions_summary(
        self,
        *,
        assistant_id: int,
        as_of_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        target_date = as_of_date or datetime.now(MSK).date()
        next_day = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT
                        kind,
                        ROUND(SUM(active_amount), 4) AS amount
                    FROM (
                        SELECT
                            s.id,
                            s.kind,
                            GREATEST(
                                ROUND(
                                    s.amount_total - COALESCE(SUM(sr.amount), 0),
                                    4
                                ),
                                0
                            ) AS active_amount
                        FROM assistant_sanctions s
                        LEFT JOIN assistant_sanction_reliefs sr
                          ON sr.sanction_id = s.id
                         AND sr.relieved_at < %s
                        WHERE s.assistant_id = %s
                          AND s.issued_at < %s
                        GROUP BY s.id, s.kind, s.amount_total
                    ) x
                    GROUP BY kind
                    """,
                    (next_day, assistant_id, next_day),
                )
                rows = await cursor.fetchall() or []
                summary = {
                    "assistant_id": assistant_id,
                    "as_of_date": target_date,
                    "check": 0.0,
                    "point": 0.0,
                    "percent": 0.0,
                    "oral": 0.0,
                    "strict": 0.0,
                }
                for row in rows:
                    kind = str(row.get("kind"))
                    summary[kind] = round(float(row.get("amount") or 0), 4)
                return summary

    @db_retry()
    async def get_assistant_active_sanctions(self, assistant_id: int) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT
                        sb.sanction_id,
                        sb.assistant_id,
                        sb.kind,
                        sb.amount_total,
                        sb.relieved_amount,
                        sb.active_amount,
                        sb.auto_relief_date,
                        sb.issued_at,
                        CASE
                            WHEN sb.source_type = 'queued_batch' AND op.queued_at IS NOT NULL
                                THEN op.queued_at
                            ELSE sb.issued_at
                        END AS display_issued_at,
                        sb.source_type,
                        sb.source_batch_id,
                        sb.basis_date,
                        sb.policy_month,
                        sb.cycle_no
                    FROM sanction_balances sb
                    LEFT JOIN sanction_operations op
                      ON op.id = sb.source_batch_id
                    WHERE sb.assistant_id = %s
                      AND sb.active_amount > 0
                    ORDER BY sb.issued_at DESC, sb.sanction_id DESC
                    """,
                    (assistant_id,),
                )
                assistant_sanctions = await cursor.fetchall() or []
                result: List[Dict[str, Any]] = []
                for sanction in assistant_sanctions:
                    sanction_id = int(sanction["sanction_id"])
                    workoff_items = await self._get_sanction_workoff_items_locked(cursor, sanction_id=sanction_id)
                    progress_items = (
                        await self._get_workoff_progress_items_locked(
                            cursor,
                            assistant_id=assistant_id,
                            workoff_items=workoff_items,
                        )
                        if workoff_items
                        else []
                    )
                    result.append(
                        {
                            **{
                                **dict(sanction),
                                "operation_id": sanction.get("source_batch_id"),
                                "settings_month": sanction.get("policy_month"),
                                "check_rule_hit_no": sanction.get("cycle_no"),
                            },
                            "workoff_items": workoff_items,
                            "workoff_progress_summary": self._build_workoff_progress_summary(progress_items),
                        }
                    )
                return result

    @db_retry()
    async def get_sanction_workoff_progress(self, sanction_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT *
                    FROM assistant_sanctions
                    WHERE id = %s
                    """,
                    (int(sanction_id),),
                )
                sanction = await cursor.fetchone()
                if not sanction:
                    return None

                workoff_items = await self._get_sanction_workoff_items_locked(
                    cursor,
                    sanction_id=int(sanction_id),
                )
                if not workoff_items:
                    return {
                        "sanction_id": sanction_id,
                        "has_workoff": False,
                    }

                assistant_id = int(sanction["assistant_id"])
                progress_items = await self._get_workoff_progress_items_locked(
                    cursor,
                    assistant_id=assistant_id,
                    workoff_items=workoff_items,
                )

                return {
                    "sanction_id": sanction_id,
                    "has_workoff": True,
                    "items": progress_items,
                    "completed_items": sum(
                        1 for item in progress_items if str(item.get("status") or "") == "completed"
                    ),
                    "total_items": len(progress_items),
                }

    @db_retry()
    async def preview_workoff_for_assistants(
        self,
        *,
        assistant_ids: List[int],
        workoff_items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized_assistant_ids = sorted({int(value) for value in assistant_ids})
        normalized_items = self._normalize_workoff_items(workoff_items)
        if not normalized_assistant_ids or not normalized_items:
            return []

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                placeholders = ", ".join(["%s"] * len(normalized_assistant_ids))
                await cursor.execute(
                    f"""
                    SELECT pr_id AS assistant_id, nickname
                    FROM assistants
                    WHERE pr_id IN ({placeholders})
                    ORDER BY nickname ASC, pr_id ASC
                    """,
                    tuple(normalized_assistant_ids),
                )
                assistant_rows = await cursor.fetchall() or []
                results: List[Dict[str, Any]] = []
                for assistant in assistant_rows:
                    assistant_id = int(assistant["assistant_id"])
                    progress_items = await self._get_workoff_progress_items_locked(
                        cursor,
                        assistant_id=assistant_id,
                        workoff_items=normalized_items,
                    )
                    results.append(
                        {
                            "assistant_id": assistant_id,
                            "nickname": assistant.get("nickname"),
                            "items": progress_items,
                        }
                    )
                return results

    @db_retry()
    async def create_manual_sanction(
        self,
        *,
        assistant_id: int,
        kind: str,
        amount: float,
        auto_relief_date: Optional[date],
        basis_date: Optional[date],
        workoff_items: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        basis = basis_date or datetime.now(MSK).date()
        month_start = self._month_start_for(basis)
        normalized_amount, normalized_auto_relief_date = self._normalize_runtime_sanction(
            kind=kind,
            amount=amount,
            auto_relief_date=auto_relief_date,
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                sanction_id = await self._insert_sanction_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind=kind,
                    amount_total=normalized_amount,
                    auto_relief_date=normalized_auto_relief_date,
                    source_type="manual",
                    basis_date=basis,
                    policy_month=month_start,
                )
                created_workoff_items = await self._create_sanction_workoff_items_locked(
                    cursor,
                    sanction_id=sanction_id,
                    workoff_items=workoff_items or [],
                )
                if created_workoff_items:
                    await self._sync_sanction_workoff_summary_locked(
                        cursor,
                        sanction_id=sanction_id,
                        workoff_items=created_workoff_items,
                    )
                cycle_result = None
                if kind == "check":
                    cycle_result = await self._apply_check_cycle_locked(
                        cursor,
                        assistant_id=assistant_id,
                        basis_date=basis,
                    )
                await conn.commit()
                return {
                    "sanction_id": sanction_id,
                    "cycle_result": cycle_result,
                }

    @db_retry()
    async def add_sanction_relief(
        self,
        *,
        sanction_id: int,
        amount: float,
        relief_type: str,
        basis_date: Optional[date],
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT sb.active_amount, s.kind
                    FROM sanction_balances sb
                    JOIN assistant_sanctions s ON s.id = sb.sanction_id
                    WHERE sb.sanction_id = %s
                    """,
                    (int(sanction_id),),
                )
                balance = await cursor.fetchone()
                if not balance:
                    return None
                active_amount = float(balance.get("active_amount") or 0)
                if active_amount <= 0:
                    return None
                kind = str(balance.get("kind") or "")
                relief_amount = round(float(amount), 4)
                if kind in {"oral", "strict"} and abs(relief_amount - 1.0) > 1e-9:
                    raise ValueError("Для устного и строгого допускается только полное снятие на 1")
                if relief_amount <= 0 or relief_amount - active_amount > 1e-9:
                    raise ValueError("Нельзя снять больше активного остатка санкции")
                await cursor.execute(
                    """
                    INSERT INTO assistant_sanction_reliefs (
                        sanction_id, amount, relieved_at, basis_date, relief_type
                    )
                    VALUES (%s, %s, CURRENT_TIMESTAMP, %s, %s)
                    """,
                    (int(sanction_id), relief_amount, basis_date, relief_type),
                )
                relief_id = int(cursor.lastrowid)
                await conn.commit()
                return {
                    "relief_id": relief_id,
                    "sanction_id": sanction_id,
                    "amount": relief_amount,
                    "relief_type": relief_type,
                    "basis_date": basis_date,
                }

    @db_retry()
    async def replace_sanction(
        self,
        *,
        sanction_id: int,
        new_kind: str,
        new_amount: float,
        new_auto_relief_date: Optional[date],
        basis_date: Optional[date],
        workoff_items: Optional[List[Dict[str, Any]]],
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT * FROM assistant_sanctions WHERE id = %s",
                    (int(sanction_id),),
                )
                existing = await cursor.fetchone()
                if not existing:
                    return None
                await self.add_sanction_relief(
                    sanction_id=sanction_id,
                    amount=float(existing.get("amount_total") or 0),
                    relief_type="replacement",
                    basis_date=basis_date,
                )
                created = await self.create_manual_sanction(
                    assistant_id=int(existing["assistant_id"]),
                    kind=new_kind,
                    amount=new_amount,
                    auto_relief_date=new_auto_relief_date,
                    basis_date=basis_date or existing.get("basis_date"),
                    workoff_items=workoff_items or [],
                )
                await cursor.execute(
                    "UPDATE assistant_sanctions SET replaced_by_sanction_id = %s WHERE id = %s",
                    (created["sanction_id"], int(sanction_id)),
                )
                await conn.commit()
                return {
                    "replaced_sanction_id": sanction_id,
                    "new_sanction_id": created["sanction_id"],
                    "cycle_result": created.get("cycle_result"),
                }
