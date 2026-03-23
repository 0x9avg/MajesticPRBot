from __future__ import annotations

from .core import (
    Any,
    CURRENT_SANCTION_POLICY_MONTH,
    Dict,
    FIXED_SIZE_SANCTION_KINDS,
    LEAVE_MANUAL_STATUSES,
    List,
    Optional,
    WARNING_SANCTION_KINDS,
    WEEKLY_MANUAL_STATUSES,
    WEEKLY_MANUAL_STATUS_NONE,
    _month_start,
    date,
    datetime,
    timedelta,
)


class SanctionsPolicyMixin:
    @staticmethod
    def _default_sanction_policy_values() -> Dict[str, Any]:
        return {
            "check_cycle_size": 5,
            "check_immunity_hours_per_day": 4,
            "point_immunity_hours_per_day": 5,
            "percent_immunity_hours_per_day": 6,
            "check_relief_hours_per_day": 4,
            "point_relief_hours_per_day": 5,
            "percent_relief_hours_per_day": 6,
            "check_relief_min_streak_days": 2,
            "point_relief_min_streak_days": 2,
            "percent_relief_min_streak_days": 2,
            "percent_relief_step_amount": 3,
            "daily_norm_spec": 4,
            "daily_norm_complaints": 0,
            "daily_norm_mchat": 0,
        }

    @staticmethod
    def _default_check_cycle_rules() -> List[tuple[int, Optional[int], str, float]]:
        return [
            (1, 2, "point", 1.0),
            (3, 3, "point", 2.0),
            (4, 5, "percent", 3.0),
            (6, 6, "percent", 5.0),
            (7, 7, "oral", 1.0),
            (8, None, "strict", 1.0),
        ]

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

        normalized_auto_relief_date = (
            auto_relief_date if safe_kind in WARNING_SANCTION_KINDS else None
        )
        if safe_kind in WARNING_SANCTION_KINDS and normalized_auto_relief_date is None:
            raise ValueError("Для устного и строгого требуется дата автоматического снятия")
        return normalized_amount, normalized_auto_relief_date

    async def _ensure_monthly_policy_row(
        self, cursor, month_start: date
    ) -> Dict[str, Any]:
        await cursor.execute(
            """
            INSERT INTO monthly_sanction_settings (
                month_start,
                check_cycle_size,
                check_immunity_hours_per_day,
                point_immunity_hours_per_day,
                percent_immunity_hours_per_day,
                check_relief_hours_per_day,
                point_relief_hours_per_day,
                percent_relief_hours_per_day,
                check_relief_min_streak_days,
                point_relief_min_streak_days,
                percent_relief_min_streak_days,
                percent_relief_step_amount,
                daily_norm_spec,
                daily_norm_complaints,
                daily_norm_mchat
            )
            VALUES (%s, 5, 4, 5, 6, 4, 5, 6, 2, 2, 2, 3, 4, 0, 0)
            ON DUPLICATE KEY UPDATE month_start = month_start
            """,
            (month_start,),
        )
        await cursor.execute(
            "SELECT * FROM monthly_sanction_settings WHERE month_start = %s",
            (month_start,),
        )
        row = await cursor.fetchone() or {}
        await cursor.execute(
            "SELECT COUNT(*) AS cnt FROM monthly_check_rules WHERE month_start = %s",
            (month_start,),
        )
        count_row = await cursor.fetchone() or {}
        if int(count_row.get("cnt", 0)) == 0:
            for range_start, range_end, penalty_kind, penalty_amount in [
                (1, 2, "point", 1.0),
                (3, 3, "point", 2.0),
                (4, 5, "percent", 3.0),
                (6, 6, "percent", 5.0),
                (7, 7, "oral", 1.0),
                (8, None, "strict", 1.0),
            ]:
                await cursor.execute(
                    """
                    INSERT INTO monthly_check_rules (
                        month_start, range_start, range_end, penalty_kind, penalty_amount
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (month_start, range_start, range_end, penalty_kind, penalty_amount),
                )
        return row

    async def _ensure_current_policy_row(self, cursor) -> Dict[str, Any]:
        current_month = CURRENT_SANCTION_POLICY_MONTH
        await cursor.execute(
            "SELECT * FROM monthly_sanction_settings WHERE month_start = %s",
            (current_month,),
        )
        row = await cursor.fetchone() or {}

        if not row:
            template = self._default_sanction_policy_values()
            await cursor.execute(
                """
                SELECT *
                FROM monthly_sanction_settings
                WHERE month_start <> %s
                ORDER BY month_start DESC
                LIMIT 1
                """,
                (current_month,),
            )
            existing = await cursor.fetchone() or {}
            for key in template:
                if existing.get(key) is not None:
                    template[key] = existing[key]

            await cursor.execute(
                """
                INSERT INTO monthly_sanction_settings (
                    month_start,
                    check_cycle_size,
                    check_immunity_hours_per_day,
                    point_immunity_hours_per_day,
                    percent_immunity_hours_per_day,
                    check_relief_hours_per_day,
                    point_relief_hours_per_day,
                    percent_relief_hours_per_day,
                    check_relief_min_streak_days,
                    point_relief_min_streak_days,
                    percent_relief_min_streak_days,
                    percent_relief_step_amount,
                    daily_norm_spec,
                    daily_norm_complaints,
                    daily_norm_mchat
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    current_month,
                    int(template["check_cycle_size"]),
                    float(template["check_immunity_hours_per_day"]),
                    float(template["point_immunity_hours_per_day"]),
                    float(template["percent_immunity_hours_per_day"]),
                    float(template["check_relief_hours_per_day"]),
                    float(template["point_relief_hours_per_day"]),
                    float(template["percent_relief_hours_per_day"]),
                    int(template["check_relief_min_streak_days"]),
                    int(template["point_relief_min_streak_days"]),
                    int(template["percent_relief_min_streak_days"]),
                    float(template["percent_relief_step_amount"]),
                    float(template["daily_norm_spec"]),
                    int(template["daily_norm_complaints"]),
                    int(template["daily_norm_mchat"]),
                ),
            )
            await cursor.execute(
                "SELECT * FROM monthly_sanction_settings WHERE month_start = %s",
                (current_month,),
            )
            row = await cursor.fetchone() or {}

        await cursor.execute(
            "SELECT COUNT(*) AS cnt FROM monthly_check_rules WHERE month_start = %s",
            (current_month,),
        )
        count_row = await cursor.fetchone() or {}
        if int(count_row.get("cnt", 0)) == 0:
            await cursor.execute(
                """
                SELECT month_start
                FROM monthly_check_rules
                WHERE month_start <> %s
                GROUP BY month_start
                ORDER BY month_start DESC
                LIMIT 1
                """,
                (current_month,),
            )
            source_month_row = await cursor.fetchone() or {}
            source_month = source_month_row.get("month_start")
            if source_month is not None:
                await cursor.execute(
                    """
                    SELECT range_start, range_end, penalty_kind, penalty_amount
                    FROM monthly_check_rules
                    WHERE month_start = %s
                    ORDER BY range_start ASC, COALESCE(range_end, 4294967295) ASC, id ASC
                    """,
                    (source_month,),
                )
                source_rules = await cursor.fetchall() or []
            else:
                source_rules = []

            rules_to_insert = source_rules or [
                {
                    "range_start": range_start,
                    "range_end": range_end,
                    "penalty_kind": penalty_kind,
                    "penalty_amount": penalty_amount,
                }
                for range_start, range_end, penalty_kind, penalty_amount in self._default_check_cycle_rules()
            ]
            for rule in rules_to_insert:
                await cursor.execute(
                    """
                    INSERT INTO monthly_check_rules (
                        month_start, range_start, range_end, penalty_kind, penalty_amount
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        current_month,
                        int(rule["range_start"]),
                        int(rule["range_end"]) if rule.get("range_end") is not None else None,
                        str(rule["penalty_kind"]),
                        float(rule["penalty_amount"]),
                    ),
                )

        return row

    @staticmethod
    def _normalize_manual_status(
        value: Any,
    ) -> Optional[str]:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        if normalized == WEEKLY_MANUAL_STATUS_NONE:
            return None
        if normalized not in WEEKLY_MANUAL_STATUSES:
            return None
        return normalized

    async def _get_day_manual_status_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        work_date: date,
    ) -> Dict[str, Any]:
        await cursor.execute(
            """
            SELECT manual_status, updated_at, updated_by_id
            FROM assistant_day_status_overrides
            WHERE assistant_id = %s
              AND work_date = %s
            LIMIT 1
            """,
            (assistant_id, work_date),
        )
        row = await cursor.fetchone() or {}
        manual_status = self._normalize_manual_status(row.get("manual_status"))
        return {
            "manual_status": manual_status,
            "is_leave_day": manual_status in LEAVE_MANUAL_STATUSES,
            "updated_at": row.get("updated_at"),
            "updated_by_id": row.get("updated_by_id"),
        }

    async def _get_day_spec_metrics_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        work_date: date,
    ) -> Dict[str, Any]:
        day_start = datetime.combine(work_date, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        await cursor.execute(
            """
            SELECT
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
            WHERE ss.pr_id = %s
              AND ss.deleted_at IS NULL
              AND ss.started_at < %s
              AND COALESCE(ss.ended_at, %s) > %s
              AND (ss.target_type <> 'event' OR e.approval_status = 'approved')
            """,
            (
                day_start,
                day_end,
                day_end,
                day_start,
                day_end,
                day_end,
                assistant_id,
                day_end,
                day_end,
                day_start,
            ),
        )
        row = await cursor.fetchone() or {}
        seconds = int(row.get("spec_seconds_on_day") or 0)
        return {
            "spec_seconds_on_day": seconds,
            "spec_hours_on_day": round(seconds / 3600.0, 4),
            "spec_points_auto": round(float(row.get("spec_points_auto") or 0), 4),
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
        policy = await self._ensure_monthly_policy_row(
            cursor,
            self._month_start_for(work_date),
        )
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

    async def _get_monthly_sanction_policy(self, month_start: date) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                row = await self._ensure_monthly_policy_row(cursor, month_start)
                await conn.commit()
                return row

    async def get_current_sanction_policy(self) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                row = dict(await self._ensure_current_policy_row(cursor))
                await conn.commit()
                row.pop("month_start", None)
                return row

    async def upsert_current_sanction_policy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed_fields = {
            "check_cycle_size",
            "check_immunity_hours_per_day",
            "point_immunity_hours_per_day",
            "percent_immunity_hours_per_day",
            "check_relief_hours_per_day",
            "point_relief_hours_per_day",
            "percent_relief_hours_per_day",
            "check_relief_min_streak_days",
            "point_relief_min_streak_days",
            "percent_relief_min_streak_days",
            "percent_relief_step_amount",
            "daily_norm_spec",
            "daily_norm_complaints",
            "daily_norm_mchat",
        }
        data = {key: value for key, value in payload.items() if key in allowed_fields}
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_current_policy_row(cursor)
                if data:
                    set_sql = ", ".join(f"{field} = %s" for field in data.keys())
                    await cursor.execute(
                        f"UPDATE monthly_sanction_settings SET {set_sql} WHERE month_start = %s",
                        tuple(data.values()) + (CURRENT_SANCTION_POLICY_MONTH,),
                    )
                await conn.commit()
        return await self.get_current_sanction_policy()

    async def _get_monthly_check_cycle_rules(self, month_start: date) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_monthly_policy_row(cursor, month_start)
                await cursor.execute(
                    """
                    SELECT
                        id,
                        month_start,
                        range_start AS cycle_from,
                        range_end AS cycle_to,
                        penalty_kind AS sanction_kind,
                        penalty_amount AS sanction_amount
                    FROM monthly_check_rules
                    WHERE month_start = %s
                    ORDER BY range_start ASC, COALESCE(range_end, 4294967295) ASC, id ASC
                    """,
                    (month_start,),
                )
                rows = await cursor.fetchall() or []
                await conn.commit()
                return rows

    async def get_current_check_cycle_rules(self) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_current_policy_row(cursor)
                await cursor.execute(
                    """
                    SELECT
                        id,
                        range_start AS cycle_from,
                        range_end AS cycle_to,
                        penalty_kind AS sanction_kind,
                        penalty_amount AS sanction_amount
                    FROM monthly_check_rules
                    WHERE month_start = %s
                    ORDER BY range_start ASC, COALESCE(range_end, 4294967295) ASC, id ASC
                    """,
                    (CURRENT_SANCTION_POLICY_MONTH,),
                )
                rows = await cursor.fetchall() or []
                await conn.commit()
                return rows

    async def replace_current_check_cycle_rules(
        self,
        rules: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not rules:
            raise ValueError("Нужно задать хотя бы одно правило галок")
        normalized_rules: List[Dict[str, Any]] = []
        for rule in rules:
            cycle_from = int(rule["cycle_from"])
            raw_cycle_to = rule.get("cycle_to")
            cycle_to = int(raw_cycle_to) if raw_cycle_to is not None else None
            if cycle_to is not None and cycle_to < cycle_from:
                raise ValueError("Диапазон правила галок задан некорректно")
            normalized_rules.append(
                {
                    "cycle_from": cycle_from,
                    "cycle_to": cycle_to,
                    "sanction_kind": str(rule["sanction_kind"]),
                    "sanction_amount": float(rule["sanction_amount"]),
                }
            )
        sorted_rules = sorted(
            normalized_rules,
            key=lambda item: (
                item["cycle_from"],
                item["cycle_to"] if item["cycle_to"] is not None else 4294967295,
            ),
        )
        for index, current in enumerate(sorted_rules):
            current_end = (
                int(current["cycle_to"])
                if current["cycle_to"] is not None
                else 4294967295
            )
            for other in sorted_rules[index + 1:]:
                if other["cycle_from"] <= current_end:
                    raise ValueError("Диапазоны правил галок не должны пересекаться")
                break

        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await self._ensure_current_policy_row(cursor)
                await cursor.execute(
                    "DELETE FROM monthly_check_rules WHERE month_start = %s",
                    (CURRENT_SANCTION_POLICY_MONTH,),
                )
                for rule in normalized_rules:
                    await cursor.execute(
                        """
                        INSERT INTO monthly_check_rules (
                            month_start, range_start, range_end, penalty_kind, penalty_amount
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            CURRENT_SANCTION_POLICY_MONTH,
                            int(rule["cycle_from"]),
                            int(rule["cycle_to"]) if rule["cycle_to"] is not None else None,
                            str(rule["sanction_kind"]),
                            float(rule["sanction_amount"]),
                        ),
                    )
                await conn.commit()
        return await self.get_current_check_cycle_rules()

    async def upsert_assistant_day_point_adjustment(
        self,
        *,
        assistant_id: int,
        work_date: date,
        delta_points: float,
    ) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO assistant_day_point_adjustments (assistant_id, work_date, delta_points)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        delta_points = VALUES(delta_points),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (assistant_id, work_date, round(float(delta_points), 4)),
                )
                await cursor.execute(
                    """
                    SELECT assistant_id, work_date, delta_points, updated_at
                    FROM assistant_day_point_adjustments
                    WHERE assistant_id = %s AND work_date = %s
                    """,
                    (assistant_id, work_date),
                )
                row = await cursor.fetchone() or {}
                await conn.commit()
                return row

    async def upsert_assistant_day_mchat(
        self,
        *,
        assistant_id: int,
        work_date: date,
        mchat_count: int,
    ) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO assistant_day_mchat (assistant_id, work_date, mchat_count)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        mchat_count = VALUES(mchat_count),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (assistant_id, work_date, max(int(mchat_count), 0)),
                )
                await cursor.execute(
                    """
                    SELECT assistant_id, work_date, mchat_count, updated_at
                    FROM assistant_day_mchat
                    WHERE assistant_id = %s AND work_date = %s
                    """,
                    (assistant_id, work_date),
                )
                row = await cursor.fetchone() or {}
                await conn.commit()
                return row

    async def get_assistant_day_status(
        self,
        *,
        assistant_id: int,
        work_date: date,
    ) -> Dict[str, Any]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                status = await self._get_assistant_day_status_locked(
                    cursor,
                    assistant_id=assistant_id,
                    work_date=work_date,
                )
                await conn.commit()
                return status
