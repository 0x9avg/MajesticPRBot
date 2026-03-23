from __future__ import annotations

from .core import (
    Any,
    Dict,
    List,
    MSK,
    Optional,
    SANCTIONS_GLOBAL_LOCK_NAME,
    date,
    datetime,
    db_retry,
    json,
    timedelta,
)


class SanctionsBatchesMixin:
    async def _acquire_named_lock(
        self,
        cursor,
        *,
        lock_name: str,
        timeout_seconds: int = 30,
    ) -> bool:
        await cursor.execute(
            "SELECT GET_LOCK(%s, %s) AS acquired",
            (lock_name, int(timeout_seconds)),
        )
        row = await cursor.fetchone()
        if isinstance(row, dict):
            return bool(row.get("acquired"))
        return bool(row[0]) if row else False

    async def _release_named_lock(self, cursor, *, lock_name: str) -> None:
        try:
            await cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
            await cursor.fetchone()
        except Exception:
            self.logger.debug(
                "Failed to release named lock %s", lock_name, exc_info=True
            )

    async def _claim_sanction_nightly_run_locked(
        self,
        cursor,
        *,
        basis_date: date,
    ) -> Dict[str, Any]:
        claimed_at = datetime.now(MSK).replace(tzinfo=None)
        stale_before = claimed_at - timedelta(seconds=3600)
        await cursor.execute(
            """
            SELECT basis_date, status, started_at, finished_at, failure_reason
            FROM sanction_nightly_runs
            WHERE basis_date = %s
            LIMIT 1
            """,
            (basis_date,),
        )
        existing = await cursor.fetchone() or {}
        status = str(existing.get("status") or "")
        started_at = existing.get("started_at")

        if not existing:
            await cursor.execute(
                """
                INSERT INTO sanction_nightly_runs (
                    basis_date,
                    status,
                    started_at,
                    finished_at,
                    failure_reason
                )
                VALUES (%s, 'processing', %s, NULL, NULL)
                """,
                (basis_date, claimed_at),
            )
            return {"claimed": True, "status": "processing", "stale_recovered": False}

        if (
            status == "processing"
            and started_at is not None
            and started_at < stale_before
        ):
            await cursor.execute(
                """
                UPDATE sanction_nightly_runs
                SET status = 'processing',
                    started_at = %s,
                    finished_at = NULL,
                    failure_reason = NULL
                WHERE basis_date = %s
                """,
                (claimed_at, basis_date),
            )
            return {"claimed": True, "status": "processing", "stale_recovered": True}

        if status == "failed":
            await cursor.execute(
                """
                UPDATE sanction_nightly_runs
                SET status = 'processing',
                    started_at = %s,
                    finished_at = NULL,
                    failure_reason = NULL
                WHERE basis_date = %s
                """,
                (claimed_at, basis_date),
            )
            return {
                "claimed": True,
                "status": "processing",
                "stale_recovered": False,
                "replayed_failed_run": True,
            }

        return {
            "claimed": False,
            "status": status or None,
            "stale_recovered": False,
            "finished_at": existing.get("finished_at"),
            "failure_reason": existing.get("failure_reason"),
        }

    async def _complete_sanction_nightly_run_locked(
        self,
        cursor,
        *,
        basis_date: date,
    ) -> None:
        await cursor.execute(
            """
            UPDATE sanction_nightly_runs
            SET status = 'completed',
                finished_at = %s,
                failure_reason = NULL
            WHERE basis_date = %s
            """,
            (datetime.now(MSK).replace(tzinfo=None), basis_date),
        )

    async def _fail_sanction_nightly_run_locked(
        self,
        cursor,
        *,
        basis_date: date,
        failure_reason: str,
    ) -> None:
        await cursor.execute(
            """
            UPDATE sanction_nightly_runs
            SET status = 'failed',
                finished_at = %s,
                failure_reason = %s
            WHERE basis_date = %s
            """,
            (
                datetime.now(MSK).replace(tzinfo=None),
                str(failure_reason or "")[:65535],
                basis_date,
            ),
        )

    async def _list_active_assistants_with_live_status_locked(
        self, cursor
    ) -> List[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT
                a.pr_id AS assistant_id,
                CASE WHEN ss.id IS NULL THEN FALSE ELSE TRUE END AS live_in_spec
            FROM assistants a
            LEFT JOIN spec_sessions ss
              ON ss.pr_id = a.pr_id
             AND ss.ended_at IS NULL
             AND ss.deleted_at IS NULL
            WHERE a.dismissed_at IS NULL
            ORDER BY a.pr_id ASC
            """
        )
        return await cursor.fetchall() or []

    async def _rebuild_batch_snapshot_locked(
        self,
        cursor,
        *,
        batch_id: int,
        explicit_assistant_ids: Optional[List[int]] = None,
    ) -> None:
        await cursor.execute(
            """
            SELECT
                id,
                operation_date AS basis_date,
                penalty_kind AS sanction_kind,
                penalty_amount AS sanction_amount,
                recipient_mode AS audience_mode,
                status
            FROM sanction_operations
            WHERE id = %s
            """,
            (batch_id,),
        )
        batch = await cursor.fetchone()
        if not batch:
            raise ValueError("Operation not found")

        audience_mode = str(batch.get("audience_mode"))
        assistants = await self._list_active_assistants_with_live_status_locked(cursor)
        assistant_status_map = {
            int(row["assistant_id"]): bool(row.get("live_in_spec"))
            for row in assistants
        }

        if explicit_assistant_ids is not None:
            selected_ids = list(
                dict.fromkeys(int(value) for value in explicit_assistant_ids)
            )
        else:
            selected_ids = []
            for assistant_id, live_in_spec in assistant_status_map.items():
                if audience_mode == "all_active":
                    selected_ids.append(assistant_id)
                elif (
                    audience_mode == "live_without_active_session" and not live_in_spec
                ):
                    selected_ids.append(assistant_id)

        await cursor.execute(
            "DELETE FROM sanction_operation_members WHERE operation_id = %s",
            (batch_id,),
        )

        for assistant_id in selected_ids:
            await cursor.execute(
                """
                INSERT INTO sanction_operation_members (
                    operation_id,
                    assistant_id,
                    issue_status,
                    issue_reason,
                    issued_sanction_id
                )
                VALUES (%s, %s, 'pending', NULL, NULL)
                """,
                (batch_id, assistant_id),
            )

    async def _get_effective_batch_members_locked(
        self,
        cursor,
        *,
        batch_id: int,
        assistant_filter: Optional[Set[int]] = None,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT *
            FROM sanction_operation_members
            WHERE operation_id = %s
        """
        params: List[Any] = [batch_id]
        if assistant_filter:
            placeholders = ", ".join(["%s"] * len(assistant_filter))
            query += f" AND assistant_id IN ({placeholders})"
            params.extend(sorted(assistant_filter))
        query += " ORDER BY assistant_id ASC"
        await cursor.execute(query, tuple(params))
        return await cursor.fetchall() or []

    async def _refresh_queued_batch_status_locked(
        self, cursor, *, batch_id: int
    ) -> Optional[str]:
        await cursor.execute(
            "SELECT status FROM sanction_operations WHERE id = %s",
            (batch_id,),
        )
        batch = await cursor.fetchone()
        if not batch:
            return None
        current_status = str(batch.get("status") or "")
        if current_status == "cancelled":
            return current_status

        await cursor.execute(
            """
            SELECT
                COUNT(*) AS effective_members,
                SUM(CASE WHEN issue_status = 'pending' THEN 1 ELSE 0 END) AS pending_members,
                SUM(CASE WHEN issue_status = 'failed' THEN 1 ELSE 0 END) AS failed_members
            FROM sanction_operation_members
            WHERE operation_id = %s
            """,
            (batch_id,),
        )
        counts = await cursor.fetchone() or {}
        pending_members = int(counts.get("pending_members") or 0)
        failed_members = int(counts.get("failed_members") or 0)

        if failed_members > 0:
            next_status = "failed"
        elif pending_members > 0:
            next_status = (
                current_status
                if current_status in {"queued", "processing"}
                else "processing"
            )
        else:
            next_status = "completed"

        await cursor.execute(
            """
            UPDATE sanction_operations
            SET status = %s,
                processed_at = CASE
                    WHEN %s IN ('completed', 'failed') THEN CURRENT_TIMESTAMP
                    ELSE processed_at
                END
            WHERE id = %s
            """,
            (next_status, next_status, batch_id),
        )
        return next_status

    async def _execute_queued_batch_locked(
        self,
        cursor,
        *,
        batch: Dict[str, Any],
        run_started_at: datetime,
        ignore_immunity: bool = False,
        assistant_filter: Optional[Set[int]] = None,
        apply_check_cycle: bool = True,
    ) -> Dict[str, Any]:
        batch_id = int(batch["id"])
        members = await self._get_effective_batch_members_locked(
            cursor,
            batch_id=batch_id,
            assistant_filter=assistant_filter,
        )
        batch_workoff_items = await self._get_batch_workoff_items_locked(
            cursor,
            batch_id=batch_id,
        )

        batch_result = {
            "batch_id": batch_id,
            "issued": [],
            "skipped_immunity": [],
            "skipped_leave": [],
            "failed": [],
            "derived": [],
        }

        for member in members:
            assistant_id = int(member["assistant_id"])
            try:
                day_status = await self._get_assistant_day_status_locked(
                    cursor,
                    assistant_id=assistant_id,
                    work_date=batch["basis_date"],
                )
                kind = str(batch["sanction_kind"])
                if not ignore_immunity and bool(day_status.get("is_leave_day")):
                    await cursor.execute(
                        """
                        UPDATE sanction_operation_members
                        SET issue_status = 'skipped_leave',
                            issue_reason = %s,
                            issued_sanction_id = NULL
                        WHERE operation_id = %s AND assistant_id = %s
                        """,
                        ("Skipped by U/O day override", batch_id, assistant_id),
                    )
                    batch_result["skipped_leave"].append(assistant_id)
                    continue
                immunity = False
                if not ignore_immunity:
                    immunity = (
                        (kind == "check" and day_status["check_immunity"])
                        or (kind == "point" and day_status["point_immunity"])
                        or (kind == "percent" and day_status["percent_immunity"])
                    )
                if immunity:
                    await cursor.execute(
                        """
                        UPDATE sanction_operation_members
                        SET issue_status = 'skipped_immunity',
                            issue_reason = %s,
                            issued_sanction_id = NULL
                        WHERE operation_id = %s AND assistant_id = %s
                        """,
                        ("Skipped by day immunity", batch_id, assistant_id),
                    )
                    batch_result["skipped_immunity"].append(assistant_id)
                    continue

                sanction_id = await self._insert_sanction_locked(
                    cursor,
                    assistant_id=assistant_id,
                    kind=kind,
                    amount_total=float(batch["sanction_amount"] or 0),
                    auto_relief_date=batch.get("auto_relief_date"),
                    issued_at=run_started_at,
                    source_type="queued_batch",
                    source_batch_id=batch_id,
                    basis_date=batch["basis_date"],
                    policy_month=self._month_start_for(batch["basis_date"]),
                )
                assistant_sanction_workoffs = (
                    await self._create_sanction_workoff_items_locked(
                        cursor,
                        sanction_id=sanction_id,
                        workoff_items=batch_workoff_items,
                    )
                )
                if assistant_sanction_workoffs:
                    await self._sync_sanction_workoff_summary_locked(
                        cursor,
                        sanction_id=sanction_id,
                        workoff_items=assistant_sanction_workoffs,
                    )
                await cursor.execute(
                    """
                    UPDATE sanction_operation_members
                    SET issue_status = 'issued',
                        issue_reason = NULL,
                        issued_sanction_id = %s
                    WHERE operation_id = %s AND assistant_id = %s
                    """,
                    (sanction_id, batch_id, assistant_id),
                )
                batch_result["issued"].append(
                    {"assistant_id": assistant_id, "sanction_id": sanction_id}
                )
                if kind == "check" and apply_check_cycle:
                    cycle_result = await self._apply_check_cycle_locked(
                        cursor,
                        assistant_id=assistant_id,
                        basis_date=batch["basis_date"],
                        source_batch_id=batch_id,
                        run_timestamp=run_started_at,
                    )
                    if cycle_result:
                        batch_result["derived"].append(cycle_result)
            except Exception as exc:
                await cursor.execute(
                    """
                    UPDATE sanction_operation_members
                    SET issue_status = 'failed',
                        issue_reason = %s,
                        issued_sanction_id = NULL
                    WHERE operation_id = %s AND assistant_id = %s
                    """,
                    (str(exc)[:255], batch_id, assistant_id),
                )
                batch_result["failed"].append(
                    {"assistant_id": assistant_id, "error": str(exc)}
                )

        return batch_result

    async def _claim_operation_for_processing_locked(
        self,
        cursor,
        *,
        operation_id: int,
        processing_mode: str,
        processed_by_id: Optional[int],
    ) -> Optional[Dict[str, Any]]:
        await cursor.execute(
            """
            UPDATE sanction_operations
            SET status = 'processing',
                processing_mode = %s,
                processed_by_id = %s
            WHERE id = %s
              AND status = 'queued'
            """,
            (processing_mode, processed_by_id, operation_id),
        )
        if cursor.rowcount <= 0:
            return None
        await cursor.execute(
            """
            SELECT
                id,
                operation_date AS basis_date,
                penalty_kind AS sanction_kind,
                penalty_amount AS sanction_amount,
                auto_relief_date,
                recipient_mode AS audience_mode,
                status,
                processing_mode,
                processed_by_id,
                queued_at,
                processed_at,
                failure_reason
            FROM sanction_operations
            WHERE id = %s
            """,
            (operation_id,),
        )
        return await cursor.fetchone()

    async def _process_single_sanction_operation_locked(
        self,
        cursor,
        *,
        operation_id: int,
        run_started_at: datetime,
        ignore_immunity: bool,
        processing_mode: str,
        processed_by_id: Optional[int] = None,
        assistant_filter: Optional[Set[int]] = None,
        apply_check_cycle: bool = True,
    ) -> Optional[Dict[str, Any]]:
        batch = await self._claim_operation_for_processing_locked(
            cursor,
            operation_id=operation_id,
            processing_mode=processing_mode,
            processed_by_id=processed_by_id,
        )
        if not batch:
            return None
        batch_result = await self._execute_queued_batch_locked(
            cursor,
            batch=batch,
            run_started_at=run_started_at,
            ignore_immunity=ignore_immunity,
            assistant_filter=assistant_filter,
            apply_check_cycle=apply_check_cycle,
        )
        new_status = await self._refresh_queued_batch_status_locked(
            cursor,
            batch_id=operation_id,
        )
        await cursor.execute(
            """
            UPDATE sanction_operations
            SET failure_reason = %s
            WHERE id = %s
            """,
            (
                (
                    json.dumps(batch_result["failed"], default=str)
                    if batch_result["failed"]
                    else None
                ),
                operation_id,
            ),
        )
        batch_result["status"] = new_status
        return batch_result

    async def _replay_check_cycles_for_day_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        basis_date: date,
        run_started_at: datetime,
    ) -> List[Dict[str, Any]]:
        await cursor.execute(
            """
            SELECT id, operation_id AS source_batch_id
            FROM assistant_sanctions
            WHERE assistant_id = %s
              AND kind = 'check'
              AND basis_date = %s
            ORDER BY issued_at ASC, id ASC
            """,
            (assistant_id, basis_date),
        )
        check_rows = await cursor.fetchall() or []
        derived: List[Dict[str, Any]] = []
        for row in check_rows:
            cycle_result = await self._apply_check_cycle_locked(
                cursor,
                assistant_id=assistant_id,
                basis_date=basis_date,
                source_batch_id=row.get("source_batch_id"),
                run_timestamp=run_started_at,
            )
            if cycle_result:
                derived.append(cycle_result)
        return derived

    async def _purge_assistant_derived_outputs_locked(
        self,
        cursor,
        *,
        assistant_id: int,
        start_date: date,
        end_date: date,
    ) -> None:
        await cursor.execute(
            """
            UPDATE sanction_operation_members m
            JOIN sanction_operations b ON b.id = m.operation_id
            SET m.issue_status = 'pending',
                m.issue_reason = NULL,
                m.issued_sanction_id = NULL
            WHERE m.assistant_id = %s
              AND b.operation_date BETWEEN %s AND %s
              AND b.status <> 'cancelled'
            """,
            (assistant_id, start_date, end_date),
        )

        await cursor.execute(
            """
            DELETE sr
            FROM assistant_sanction_reliefs sr
            JOIN assistant_sanctions s ON s.id = sr.sanction_id
            WHERE s.assistant_id = %s
              AND sr.basis_date BETWEEN %s AND %s
              AND sr.relief_type IN ('default', 'custom_workoff', 'cycle_reset', 'month_reset', 'auto_expire')
            """,
            (assistant_id, start_date, end_date),
        )

        await cursor.execute(
            """
            SELECT id
            FROM assistant_sanctions
            WHERE assistant_id = %s
              AND basis_date BETWEEN %s AND %s
              AND source_type IN ('queued_batch', 'check_cycle')
            """,
            (assistant_id, start_date, end_date),
        )
        sanction_rows = await cursor.fetchall() or []
        sanction_ids = [int(row["id"]) for row in sanction_rows]
        if sanction_ids:
            placeholders = ", ".join(["%s"] * len(sanction_ids))
            await cursor.execute(
                f"DELETE FROM assistant_sanction_reliefs WHERE sanction_id IN ({placeholders})",
                tuple(sanction_ids),
            )
            await cursor.execute(
                f"DELETE FROM assistant_sanctions WHERE id IN ({placeholders})",
                tuple(sanction_ids),
            )

    @db_retry()
    async def process_queued_sanction_batches_for_date(
        self,
        basis_date: date,
        *,
        force: bool = False,
    ) -> Dict[str, Any]:
        nightly_context = self._nightly_run_context_for_basis_date(basis_date)
        processing_date = nightly_context["processing_date"]
        run_started_at = nightly_context["run_started_at"]
        if not force and self._current_msk_date() < processing_date:
            return {
                "basis_date": basis_date,
                "processing_date": processing_date,
                "processed_batches": [],
                "custom_workoff": {"relieved": []},
                "warning_auto_expiry": {"relieved": []},
                "default_relief": {"relieved": []},
                "month_reset": {"reset_count": 0},
                "nightly_run": {"claimed": False, "status": "too_early"},
                "skipped": True,
            }
        processed_batches: List[Dict[str, Any]] = []
        custom_workoff_result: Dict[str, Any] = {"relieved": []}
        warning_auto_expiry_result: Dict[str, Any] = {"relieved": []}
        relief_result: Dict[str, Any] = {"relieved": []}
        month_reset_result: Dict[str, Any] = {"reset_count": 0}
        nightly_run_state: Dict[str, Any] = {"claimed": False, "status": None}
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                acquired = await self._acquire_named_lock(
                    cursor,
                    lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                )
                if not acquired:
                    raise RuntimeError("Timed out acquiring sanctions processing lock")
                try:
                    nightly_run_state = await self._claim_sanction_nightly_run_locked(
                        cursor,
                        basis_date=basis_date,
                    )
                    if not nightly_run_state.get("claimed"):
                        await conn.commit()
                        return {
                            "basis_date": basis_date,
                            "processing_date": processing_date,
                            "processed_batches": [],
                            "custom_workoff": {"relieved": []},
                            "warning_auto_expiry": {"relieved": []},
                            "default_relief": {"relieved": []},
                            "month_reset": {"reset_count": 0},
                            "nightly_run": nightly_run_state,
                            "skipped": True,
                        }
                    await cursor.execute(
                        """
                        SELECT
                            id
                        FROM sanction_operations
                        WHERE operation_date = %s
                          AND status = 'queued'
                        ORDER BY id ASC
                        """,
                        (basis_date,),
                    )
                    batches = await cursor.fetchall() or []

                    for batch in batches:
                        batch_result = (
                            await self._process_single_sanction_operation_locked(
                                cursor,
                                operation_id=int(batch["id"]),
                                run_started_at=run_started_at,
                                ignore_immunity=False,
                                processing_mode="nightly_auto",
                                processed_by_id=None,
                            )
                        )
                        if batch_result:
                            processed_batches.append(batch_result)

                    custom_workoff_result = (
                        await self._apply_custom_workoff_relief_locked(
                            cursor,
                            basis_date=basis_date,
                            run_started_at=run_started_at,
                        )
                    )
                    relief_result = await self._apply_default_auto_relief_locked(
                        cursor,
                        basis_date=basis_date,
                        run_started_at=run_started_at,
                    )
                    warning_auto_expiry_result = (
                        await self._apply_warning_auto_expiry_locked(
                            cursor,
                            current_date=processing_date,
                            run_started_at=run_started_at,
                        )
                    )
                    month_reset_result = await self._apply_month_end_check_reset_locked(
                        cursor,
                        basis_date=basis_date,
                        run_started_at=run_started_at,
                    )
                    await self._complete_sanction_nightly_run_locked(
                        cursor,
                        basis_date=basis_date,
                    )
                    nightly_run_state = {**nightly_run_state, "status": "completed"}
                    await conn.commit()
                except Exception as exc:
                    await self._fail_sanction_nightly_run_locked(
                        cursor,
                        basis_date=basis_date,
                        failure_reason=str(exc),
                    )
                    await conn.commit()
                    raise
                finally:
                    await self._release_named_lock(
                        cursor,
                        lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                    )
        return {
            "basis_date": basis_date,
            "processing_date": processing_date,
            "processed_batches": processed_batches,
            "custom_workoff": custom_workoff_result,
            "warning_auto_expiry": warning_auto_expiry_result,
            "default_relief": relief_result,
            "month_reset": month_reset_result,
            "nightly_run": nightly_run_state,
            "skipped": False,
        }

    @db_retry()
    async def process_sanction_operation_now(
        self,
        operation_id: int,
        *,
        requested_by_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        run_started_at = datetime.now(MSK).replace(tzinfo=None)
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                acquired = await self._acquire_named_lock(
                    cursor,
                    lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                )
                if not acquired:
                    raise RuntimeError("Timed out acquiring sanctions processing lock")
                try:
                    result = await self._process_single_sanction_operation_locked(
                        cursor,
                        operation_id=int(operation_id),
                        run_started_at=run_started_at,
                        ignore_immunity=True,
                        processing_mode="manual_now",
                        processed_by_id=requested_by_id,
                    )
                    if result is None:
                        await cursor.execute(
                            "SELECT status FROM sanction_operations WHERE id = %s",
                            (int(operation_id),),
                        )
                        operation = await cursor.fetchone()
                        await conn.commit()
                        return {
                            "operation_id": int(operation_id),
                            "processed": False,
                            "status": operation.get("status") if operation else None,
                            "missing": operation is None,
                        }
                    await conn.commit()
                    return {
                        "operation_id": int(operation_id),
                        "processed": True,
                        **result,
                    }
                finally:
                    await self._release_named_lock(
                        cursor,
                        lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                    )

    @db_retry()
    async def _recalculate_assistant_sanction_derivations(
        self,
        *,
        assistant_id: int,
        start_date: date,
        end_date: Optional[date] = None,
    ) -> Dict[str, Any]:
        today_msk = self._current_msk_date()
        last_closed_day = today_msk - timedelta(days=1)
        replay_end = min(end_date or last_closed_day, last_closed_day)
        if start_date > replay_end:
            return {
                "assistant_id": assistant_id,
                "start_date": start_date,
                "end_date": replay_end,
                "replayed_days": [],
                "skipped": True,
            }

        replayed_days: List[Dict[str, Any]] = []
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                acquired = await self._acquire_named_lock(
                    cursor,
                    lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                )
                if not acquired:
                    raise RuntimeError("Timed out acquiring sanctions replay lock")
                try:
                    await self._purge_assistant_derived_outputs_locked(
                        cursor,
                        assistant_id=assistant_id,
                        start_date=start_date,
                        end_date=replay_end,
                    )

                    cursor_day = start_date
                    while cursor_day <= replay_end:
                        run_started_at = datetime.combine(
                            cursor_day + timedelta(days=1),
                            datetime.min.time(),
                        )
                        await cursor.execute(
                            """
                            SELECT
                                id,
                                operation_date AS basis_date,
                                penalty_kind AS sanction_kind,
                                penalty_amount AS sanction_amount,
                                recipient_mode AS audience_mode,
                                status,
                                queued_at,
                                processed_at,
                                failure_reason
                            FROM sanction_operations
                            WHERE operation_date = %s
                              AND status IN ('processing', 'completed', 'failed')
                            ORDER BY id ASC
                            """,
                            (cursor_day,),
                        )
                        batches = await cursor.fetchall() or []
                        day_result = {
                            "basis_date": cursor_day,
                            "batches": [],
                            "derived": [],
                            "custom_workoff": None,
                            "warning_auto_expiry": None,
                            "default_relief": None,
                            "month_reset": None,
                        }

                        for batch in batches:
                            batch_result = await self._execute_queued_batch_locked(
                                cursor,
                                batch=batch,
                                run_started_at=run_started_at,
                                assistant_filter={assistant_id},
                                apply_check_cycle=False,
                            )
                            await self._refresh_queued_batch_status_locked(
                                cursor,
                                batch_id=int(batch["id"]),
                            )
                            await cursor.execute(
                                """
                                UPDATE sanction_operations
                                SET failure_reason = %s
                                WHERE id = %s
                                """,
                                (
                                    (
                                        json.dumps(batch_result["failed"], default=str)
                                        if batch_result["failed"]
                                        else None
                                    ),
                                    int(batch["id"]),
                                ),
                            )
                            day_result["batches"].append(batch_result)

                        day_result["derived"] = (
                            await self._replay_check_cycles_for_day_locked(
                                cursor,
                                assistant_id=assistant_id,
                                basis_date=cursor_day,
                                run_started_at=run_started_at,
                            )
                        )
                        day_result["custom_workoff"] = (
                            await self._apply_custom_workoff_relief_locked(
                                cursor,
                                basis_date=cursor_day,
                                run_started_at=run_started_at,
                                assistant_filter={assistant_id},
                            )
                        )
                        day_result["warning_auto_expiry"] = (
                            await self._apply_warning_auto_expiry_locked(
                                cursor,
                                current_date=run_started_at.date(),
                                run_started_at=run_started_at,
                                assistant_filter={assistant_id},
                            )
                        )
                        day_result["default_relief"] = (
                            await self._apply_default_auto_relief_locked(
                                cursor,
                                basis_date=cursor_day,
                                run_started_at=run_started_at,
                                assistant_filter={assistant_id},
                            )
                        )
                        day_result["month_reset"] = (
                            await self._apply_month_end_check_reset_locked(
                                cursor,
                                basis_date=cursor_day,
                                run_started_at=run_started_at,
                                assistant_filter={assistant_id},
                            )
                        )
                        replayed_days.append(day_result)
                        cursor_day += timedelta(days=1)

                    await conn.commit()
                finally:
                    await self._release_named_lock(
                        cursor,
                        lock_name=SANCTIONS_GLOBAL_LOCK_NAME,
                    )

        return {
            "assistant_id": assistant_id,
            "start_date": start_date,
            "end_date": replay_end,
            "replayed_days": replayed_days,
            "skipped": False,
        }

    @db_retry()
    async def create_queued_sanction_batch(
        self,
        *,
        basis_date: date,
        created_by_id: Optional[int],
        sanction_kind: str,
        sanction_amount: float,
        auto_relief_date: Optional[date],
        audience_mode: str,
        assistant_ids: Optional[List[int]],
        workoff_items: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        assistant_ids = [int(v) for v in (assistant_ids or [])]
        normalized_amount, normalized_auto_relief_date = (
            self._normalize_runtime_sanction(
                kind=sanction_kind,
                amount=sanction_amount,
                auto_relief_date=auto_relief_date,
            )
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO sanction_operations (
                        operation_date,
                        created_at,
                        created_by_id,
                        penalty_kind,
                        penalty_amount,
                        auto_relief_date,
                        recipient_mode,
                        status,
                        queued_at
                    )
                    VALUES (%s, CURRENT_TIMESTAMP, %s, %s, %s, %s, %s, 'queued', CURRENT_TIMESTAMP)
                    """,
                    (
                        basis_date,
                        created_by_id,
                        sanction_kind,
                        normalized_amount,
                        normalized_auto_relief_date,
                        audience_mode,
                    ),
                )
                batch_id = int(cursor.lastrowid)
                await self._rebuild_batch_snapshot_locked(
                    cursor,
                    batch_id=batch_id,
                    explicit_assistant_ids=assistant_ids if assistant_ids else None,
                )
                await self._replace_batch_workoff_items_locked(
                    cursor,
                    batch_id=batch_id,
                    workoff_items=workoff_items or [],
                )

                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def update_queued_sanction_batch(
        self,
        *,
        batch_id: int,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        allowed_fields = {
            "sanction_kind",
            "sanction_amount",
            "auto_relief_date",
            "audience_mode",
        }
        data = {key: value for key, value in payload.items() if key in allowed_fields}
        workoff_items = payload.get("workoff_items")
        assistant_ids = payload.get("assistant_ids")
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT status, penalty_kind, penalty_amount, auto_relief_date
                    FROM sanction_operations
                    WHERE id = %s
                    """,
                    (batch_id,),
                )
                existing = await cursor.fetchone()
                if not existing:
                    return None
                if existing.get("status") != "queued":
                    raise ValueError("Operation cannot be edited in current status")
                if any(
                    field in data
                    for field in (
                        "sanction_kind",
                        "sanction_amount",
                        "auto_relief_date",
                    )
                ):
                    effective_kind = str(
                        data.get("sanction_kind") or existing.get("penalty_kind")
                    )
                    normalized_amount, normalized_auto_relief_date = (
                        self._normalize_runtime_sanction(
                            kind=effective_kind,
                            amount=float(
                                data.get("sanction_amount")
                                if data.get("sanction_amount") is not None
                                else existing.get("penalty_amount") or 0
                            ),
                            auto_relief_date=data.get(
                                "auto_relief_date", existing.get("auto_relief_date")
                            ),
                        )
                    )
                    data["sanction_kind"] = effective_kind
                    data["sanction_amount"] = normalized_amount
                    data["auto_relief_date"] = normalized_auto_relief_date
                column_map = {
                    "sanction_kind": "penalty_kind",
                    "sanction_amount": "penalty_amount",
                    "auto_relief_date": "auto_relief_date",
                    "audience_mode": "recipient_mode",
                }
                if data:
                    set_sql = ", ".join(
                        f"{column_map[field]} = %s" for field in data.keys()
                    )
                    await cursor.execute(
                        f"UPDATE sanction_operations SET {set_sql} WHERE id = %s",
                        tuple(data.values()) + (batch_id,),
                    )
                if workoff_items is not None:
                    await self._replace_batch_workoff_items_locked(
                        cursor,
                        batch_id=batch_id,
                        workoff_items=workoff_items,
                    )
                if assistant_ids is not None:
                    await self._rebuild_batch_snapshot_locked(
                        cursor,
                        batch_id=batch_id,
                        explicit_assistant_ids=[int(v) for v in assistant_ids],
                    )
                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def add_queued_batch_member(
        self,
        *,
        batch_id: int,
        assistant_id: int,
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT status FROM sanction_operations WHERE id = %s",
                    (batch_id,),
                )
                batch = await cursor.fetchone()
                if not batch:
                    return None
                if batch.get("status") != "queued":
                    raise ValueError("Operation cannot be edited in current status")
                await cursor.execute(
                    """
                    SELECT 1
                    FROM sanction_operation_members
                    WHERE operation_id = %s AND assistant_id = %s
                    """,
                    (batch_id, assistant_id),
                )
                if await cursor.fetchone():
                    raise ValueError("Ассистент уже добавлен в эту выдачу")
                await cursor.execute(
                    """
                    INSERT INTO sanction_operation_members (
                        operation_id,
                        assistant_id,
                        issue_status,
                        issue_reason,
                        issued_sanction_id
                    )
                    VALUES (%s, %s, 'pending', NULL, NULL)
                    """,
                    (batch_id, assistant_id),
                )
                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def remove_queued_batch_member(
        self,
        *,
        batch_id: int,
        assistant_id: int,
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT status FROM sanction_operations WHERE id = %s",
                    (batch_id,),
                )
                batch = await cursor.fetchone()
                if not batch:
                    return None
                if batch.get("status") != "queued":
                    raise ValueError("Operation cannot be edited in current status")
                await cursor.execute(
                    """
                    DELETE FROM sanction_operation_members
                    WHERE operation_id = %s AND assistant_id = %s
                    """,
                    (batch_id, assistant_id),
                )
                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    @db_retry()
    async def cancel_queued_sanction_batch(
        self, batch_id: int
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT status FROM sanction_operations WHERE id = %s",
                    (batch_id,),
                )
                batch = await cursor.fetchone()
                if not batch:
                    return None
                if batch.get("status") != "queued":
                    raise ValueError("Operation cannot be cancelled in current status")
                await cursor.execute(
                    """
                    UPDATE sanction_operations
                    SET status = 'cancelled', cancelled_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND status = 'queued'
                    """,
                    (batch_id,),
                )
                await conn.commit()
        return await self.get_queued_sanction_batch(batch_id)

    @db_retry()
    async def list_queued_sanction_batches(
        self, *, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                where_sql = ""
                params: List[Any] = []
                if status:
                    where_sql = "WHERE b.status = %s"
                    params.append(status)
                else:
                    where_sql = "WHERE b.status <> 'cancelled'"
                await cursor.execute(
                    f"""
                    SELECT
                        b.id,
                        b.operation_date AS basis_date,
                        b.created_at,
                        b.created_by_id,
                        COALESCE(created_assistant.nickname, created_user.username) AS created_by_name,
                        b.penalty_kind AS sanction_kind,
                        b.penalty_amount AS sanction_amount,
                        b.auto_relief_date,
                        b.recipient_mode AS audience_mode,
                        b.status,
                        b.processing_mode,
                        b.processed_by_id,
                        COALESCE(processed_assistant.nickname, processed_user.username) AS processed_by_name,
                        b.queued_at,
                        b.processed_at,
                        b.cancelled_at,
                        b.failure_reason,
                        COUNT(m.assistant_id) AS members_total,
                        COUNT(m.assistant_id) AS effective_members,
                        SUM(CASE WHEN m.issue_status = 'issued' THEN 1 ELSE 0 END) AS issued_members,
                        SUM(CASE WHEN m.issue_status = 'skipped_immunity' THEN 1 ELSE 0 END) AS skipped_immunity_members,
                        SUM(CASE WHEN m.issue_status = 'skipped_leave' THEN 1 ELSE 0 END) AS skipped_leave_members
                    FROM sanction_operations b
                    LEFT JOIN sanction_operation_members m ON m.operation_id = b.id
                    LEFT JOIN web_auth created_user ON created_user.discord_id = b.created_by_id
                    LEFT JOIN assistants created_assistant ON created_assistant.pr_id = b.created_by_id
                    LEFT JOIN web_auth processed_user ON processed_user.discord_id = b.processed_by_id
                    LEFT JOIN assistants processed_assistant ON processed_assistant.pr_id = b.processed_by_id
                    {where_sql}
                    GROUP BY b.id
                    ORDER BY b.created_at DESC, b.id DESC
                    """,
                    tuple(params),
                )
                return await cursor.fetchall() or []

    @db_retry()
    async def get_queued_sanction_batch(
        self, batch_id: int
    ) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    SELECT
                        b.id,
                        b.operation_date AS basis_date,
                        b.created_at,
                        b.created_by_id,
                        COALESCE(created_assistant.nickname, created_user.username) AS created_by_name,
                        b.penalty_kind AS sanction_kind,
                        b.penalty_amount AS sanction_amount,
                        b.auto_relief_date,
                        b.recipient_mode AS audience_mode,
                        b.status,
                        b.processing_mode,
                        b.processed_by_id,
                        COALESCE(processed_assistant.nickname, processed_user.username) AS processed_by_name,
                        b.queued_at,
                        b.processed_at,
                        b.cancelled_at,
                        b.failure_reason,
                        COUNT(m.assistant_id) AS members_total,
                        COUNT(m.assistant_id) AS effective_members,
                        SUM(CASE WHEN m.issue_status = 'issued' THEN 1 ELSE 0 END) AS issued_members,
                        SUM(CASE WHEN m.issue_status = 'skipped_immunity' THEN 1 ELSE 0 END) AS skipped_immunity_members,
                        SUM(CASE WHEN m.issue_status = 'skipped_leave' THEN 1 ELSE 0 END) AS skipped_leave_members
                    FROM sanction_operations b
                    LEFT JOIN sanction_operation_members m ON m.operation_id = b.id
                    LEFT JOIN web_auth created_user ON created_user.discord_id = b.created_by_id
                    LEFT JOIN assistants created_assistant ON created_assistant.pr_id = b.created_by_id
                    LEFT JOIN web_auth processed_user ON processed_user.discord_id = b.processed_by_id
                    LEFT JOIN assistants processed_assistant ON processed_assistant.pr_id = b.processed_by_id
                    WHERE b.id = %s
                    GROUP BY b.id
                    """,
                    (batch_id,),
                )
                batch = await cursor.fetchone()
                if not batch:
                    return None
                await cursor.execute(
                    """
                    SELECT
                        m.operation_id AS batch_id,
                        m.assistant_id,
                        m.issue_status AS execution_status,
                        m.issue_reason AS execution_reason,
                        m.issued_sanction_id,
                        a.nickname
                    FROM sanction_operation_members m
                    LEFT JOIN assistants a ON a.pr_id = m.assistant_id
                    WHERE m.operation_id = %s
                    ORDER BY a.nickname ASC, m.assistant_id ASC
                    """,
                    (batch_id,),
                )
                batch["members"] = await cursor.fetchall() or []
                batch["workoff_items"] = await self._get_batch_workoff_items_locked(
                    cursor,
                    batch_id=batch_id,
                )
                return batch
