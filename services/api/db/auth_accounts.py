from __future__ import annotations

from .core import Any, Dict, List, MSK, Optional, date, datetime, hashlib


class AuthAccountsMixin:
    async def create_user(
        self,
        discord_id: int,
        username: str,
        password_hash: str,
        created_by: Optional[int] = None,
    ) -> int:
        """Create a new web user (web_auth) and return its PK (discord_id)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO web_auth (discord_id, username, password_hash, created_at) 
                        VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                        """,
                        (discord_id, username, password_hash),
                    )
                    await conn.commit()
                    return discord_id
        except Exception as e:
            self.logger.error(f"Failed to create user {username}: {e}", exc_info=True)
            raise

    async def create_user_with_assistant(
        self,
        discord_id: int,
        username: str,
        password_hash: str,
        nickname: str,
        role: str,
        appointed_at: Optional[date] = None,
        experience_days: int = 0,
        created_by: Optional[int] = None,
    ) -> int:
        """Create web_auth and assistant records in a single transaction."""
        try:
            async with self.pool.acquire() as conn:
                try:
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            """
                            INSERT INTO web_auth (discord_id, username, password_hash, created_at)
                            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                            """,
                            (discord_id, username, password_hash),
                        )

                        if appointed_at is not None:
                            appointed_at_dt = datetime.combine(
                                appointed_at,
                                datetime.min.time(),
                                tzinfo=MSK,
                            )
                            await cursor.execute(
                                """
                                INSERT INTO assistants (pr_id, nickname, role, appointed_at)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (discord_id, nickname, role, appointed_at_dt),
                            )
                        else:
                            await cursor.execute(
                                """
                                INSERT INTO assistants (pr_id, nickname, role, appointed_at)
                                VALUES (%s, %s, %s, DATE_SUB(CURRENT_TIMESTAMP, INTERVAL %s DAY))
                                """,
                                (discord_id, nickname, role, experience_days),
                            )

                        await conn.commit()
                        return discord_id
                except Exception:
                    await conn.rollback()
                    raise
        except Exception as e:
            self.logger.error(
                f"Failed to create user+assistant {username}: {e}",
                exc_info=True,
            )
            raise

    async def get_user_account(self, discord_id: int) -> Optional[Dict[str, Any]]:
        """Get a web account with assistant linkage details for lifecycle actions."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            w.discord_id,
                            w.username,
                            w.is_active,
                            a.pr_id AS assistant_pr_id,
                            a.nickname,
                            a.role,
                            a.dismissed_at
                        FROM web_auth w
                        LEFT JOIN assistants a ON a.pr_id = w.discord_id
                        WHERE w.discord_id = %s
                        LIMIT 1
                        """,
                        (discord_id,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(
                f"Failed to get user account {discord_id}: {e}",
                exc_info=True,
            )
            raise

    async def count_active_users_with_role(self, role: str) -> int:
        """Count active linked user accounts for a staff role."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT COUNT(*) AS total
                        FROM web_auth w
                        INNER JOIN assistants a ON a.pr_id = w.discord_id
                        WHERE w.is_active = TRUE
                          AND a.dismissed_at IS NULL
                          AND a.role = %s
                        """,
                        (role,),
                    )
                    row = await cursor.fetchone()
                    return int((row or {}).get("total") or 0)
        except Exception as e:
            self.logger.error(
                f"Failed to count active users for role {role}: {e}",
                exc_info=True,
            )
            raise

    async def update_user_role_with_assistant(
        self,
        discord_id: int,
        role: str,
    ) -> Optional[Dict[str, Any]]:
        """Update the linked assistant role for an existing account."""
        try:
            async with self.pool.acquire() as conn:
                try:
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            """
                            SELECT
                                w.discord_id,
                                w.username,
                                w.is_active,
                                a.pr_id AS assistant_pr_id,
                                a.nickname,
                                a.role,
                                a.dismissed_at
                            FROM web_auth w
                            LEFT JOIN assistants a ON a.pr_id = w.discord_id
                            WHERE w.discord_id = %s
                            LIMIT 1
                            FOR UPDATE
                            """,
                            (discord_id,),
                        )
                        account = await cursor.fetchone()
                        if not account:
                            await conn.rollback()
                            return None
                        if account.get("assistant_pr_id") is None:
                            raise RuntimeError(
                                "User account is not linked to assistant profile"
                            )

                        await cursor.execute(
                            """
                            UPDATE assistants
                            SET role = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE pr_id = %s
                            """,
                            (role, discord_id),
                        )
                        await conn.commit()
                        account["role"] = role
                        return account
                except Exception:
                    await conn.rollback()
                    raise
        except Exception as e:
            self.logger.error(
                f"Failed to update assistant role for {discord_id}: {e}",
                exc_info=True,
            )
            raise

    async def deactivate_user_with_assistant(
        self,
        discord_id: int,
        actor_id: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Deactivate a user account, dismiss assistant profile, and revoke sessions."""
        try:
            async with self.pool.acquire() as conn:
                try:
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            """
                            SELECT
                                w.discord_id,
                                w.username,
                                w.is_active,
                                a.pr_id AS assistant_pr_id,
                                a.nickname,
                                a.role,
                                a.dismissed_at
                            FROM web_auth w
                            LEFT JOIN assistants a ON a.pr_id = w.discord_id
                            WHERE w.discord_id = %s
                            LIMIT 1
                            FOR UPDATE
                            """,
                            (discord_id,),
                        )
                        account = await cursor.fetchone()
                        if not account:
                            await conn.rollback()
                            return None
                        if account.get("assistant_pr_id") is None:
                            raise RuntimeError(
                                "User account is not linked to assistant profile"
                            )

                        await cursor.execute(
                            """
                            UPDATE web_auth
                            SET is_active = FALSE
                            WHERE discord_id = %s
                            """,
                            (discord_id,),
                        )
                        await cursor.execute(
                            """
                            UPDATE assistants
                            SET dismissed_at = COALESCE(dismissed_at, CURRENT_TIMESTAMP),
                                updated_at = CURRENT_TIMESTAMP
                            WHERE pr_id = %s
                            """,
                            (discord_id,),
                        )
                        await cursor.execute(
                            """
                            UPDATE sessions
                            SET revoked = TRUE,
                                revoked_at = CURRENT_TIMESTAMP
                            WHERE user_id = %s
                              AND revoked = FALSE
                            """,
                            (discord_id,),
                        )
                        await conn.commit()
                        account["is_active"] = False
                        if account.get("dismissed_at") is None:
                            account["dismissed_at"] = datetime.utcnow()
                        if actor_id is not None or reason:
                            self.logger.info(
                                "Deactivated user %s by actor=%s reason=%s",
                                discord_id,
                                actor_id,
                                reason,
                            )
                        return account
                except Exception:
                    await conn.rollback()
                    raise
        except Exception as e:
            self.logger.error(
                f"Failed to deactivate user {discord_id}: {e}",
                exc_info=True,
            )
            raise

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username (joins assistants for role and role_permissions)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            w.discord_id,
                            w.username,
                            w.password_hash,
                            w.is_active,
                            w.require_password_change,
                            w.failed_login_attempts,
                            w.last_failed_login,
                            w.last_login,
                            w.created_at,
                            COALESCE(a.role, 'employee') AS role,
                            COALESCE(a.nickname, w.username) AS nickname,
                            rp.permissions
                        FROM web_auth w
                        LEFT JOIN assistants a ON a.pr_id = w.discord_id
                        LEFT JOIN role_permissions rp ON rp.role = COALESCE(a.role, 'employee')
                        WHERE w.username = %s
                        """,
                        (username,),
                    )
                    user = await cursor.fetchone()
                    if user and user.get("permissions"):
                        user["permissions"] = self._normalize_role_permissions_for_catalog(
                            user.get("permissions", {})
                        )
                    return user
        except Exception as e:
            self.logger.error(f"Failed to get user {username}: {e}", exc_info=True)
            raise

    async def get_user_by_discord_id(self, discord_id: int) -> Optional[Dict[str, Any]]:
        """Get user by Discord ID (joins assistants for role and role_permissions)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT
                            w.discord_id,
                            w.username,
                            w.password_hash,
                            w.is_active,
                            w.require_password_change,
                            w.failed_login_attempts,
                            w.last_failed_login,
                            w.last_login,
                            w.created_at,
                            COALESCE(a.role, 'employee') AS role,
                            COALESCE(a.nickname, w.username) AS nickname,
                            rp.permissions
                        FROM web_auth w
                        LEFT JOIN assistants a ON a.pr_id = w.discord_id
                        LEFT JOIN role_permissions rp ON rp.role = COALESCE(a.role, 'employee')
                        WHERE w.discord_id = %s
                        """,
                        (discord_id,),
                    )
                    user = await cursor.fetchone()
                    if user and user.get("permissions"):
                        user["permissions"] = self._normalize_role_permissions_for_catalog(
                            user.get("permissions", {})
                        )
                    return user
        except Exception as e:
            self.logger.error(
                f"Failed to get user by discord_id {discord_id}: {e}", exc_info=True
            )
            raise

    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID (joins assistants for role and role_permissions for permissions)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Assuming id is web_auth.id
                    await cursor.execute(
                        """
                        SELECT w.discord_id as id, w.discord_id, w.username, w.is_active, w.require_password_change, w.failed_login_attempts, w.last_login, w.created_at, 
                        COALESCE(a.role, 'employee') as role, 
                        COALESCE(a.nickname, w.username) as nickname,
                        rp.permissions
                        FROM web_auth w
                        LEFT JOIN assistants a ON a.pr_id = w.discord_id
                        LEFT JOIN role_permissions rp ON rp.role = COALESCE(a.role, 'employee')
                        WHERE w.discord_id = %s
                        """,
                        (user_id,),
                    )
                    user = await cursor.fetchone()
                    if user:
                        user["permissions"] = self._normalize_role_permissions_for_catalog(
                            user.get("permissions", {})
                        )
                    return user
        except Exception as e:
            self.logger.error(f"Failed to get user {user_id}: {e}", exc_info=True)
            raise

    async def increment_failed_login(self, username: str) -> None:
        """Increment failed login attempts."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE web_auth 
                        SET failed_login_attempts = failed_login_attempts + 1, 
                            last_failed_login = CURRENT_TIMESTAMP
                        WHERE username = %s
                        """,
                        (username,),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to increment login stats: {e}", exc_info=True)

    async def reset_failed_login(self, user_id: int) -> None:
        """Reset failed login attempts and update last login."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE web_auth 
                        SET failed_login_attempts = 0, 
                            last_failed_login = NULL,
                            last_login = CURRENT_TIMESTAMP
                        WHERE discord_id = %s
                        """,
                        (user_id,),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to reset login stats: {e}", exc_info=True)

    async def create_session(
        self,
        user_id: int,
        refresh_token_hash: str,
        family_id: str,
        expires_at,
        ip: str,
        user_agent: str,
    ) -> int:
        """Create a new session with hashed refresh token and family chain."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO sessions 
                            (user_id, refresh_token_hash, family_id, expires_at, ip_address, last_ip, user_agent) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (user_id, refresh_token_hash, family_id, expires_at, ip, ip, user_agent),
                    )
                    await conn.commit()
                    return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Failed to create session: {e}", exc_info=True)
            raise

    async def find_session_by_refresh_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        """Find a session by its refresh token hash (active or replaced)."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT id, user_id, refresh_token_hash, family_id, 
                               replaced_by_hash, expires_at, created_at,
                               revoked, revoked_at, ip_address, last_ip, user_agent
                        FROM sessions
                        WHERE refresh_token_hash = %s
                        LIMIT 1
                        """,
                        (token_hash,),
                    )
                    return await cursor.fetchone()
        except Exception as e:
            self.logger.error(f"Failed to find session by hash: {e}", exc_info=True)
            return None

    async def rotate_session(
        self,
        old_session_id: int,
        old_token_hash: str,
        new_token_hash: str,
        new_expires_at,
        new_ip: str,
        new_user_agent: str,
    ) -> Optional[int]:
        """
        Atomically rotate a refresh token: mark old as replaced, create new session in same family.

        Returns new session_id or None if the old session was already rotated/revoked (reuse detection).
        """
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    # Lock the old session to prevent race conditions
                    await cursor.execute(
                        """
                        SELECT id, user_id, family_id, refresh_token_hash, 
                               revoked, replaced_by_hash, expires_at
                        FROM sessions
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (old_session_id,),
                    )
                    old_session = await cursor.fetchone()

                    if not old_session:
                        return None

                    # Reuse detection: if already replaced or revoked, it's a replay/theft
                    replaced_by_hash = old_session.get("replaced_by_hash")
                    if (
                        (replaced_by_hash is not None and str(replaced_by_hash).strip() != "")
                        or old_session["revoked"]
                    ):
                        return None  # Caller must handle reuse detection

                    # Mark old session as replaced
                    await cursor.execute(
                        """
                        UPDATE sessions 
                        SET replaced_by_hash = %s, revoked = TRUE, revoked_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        (new_token_hash, old_session_id),
                    )

                    # Create new session in the same family
                    await cursor.execute(
                        """
                        INSERT INTO sessions 
                            (user_id, refresh_token_hash, family_id, expires_at, ip_address, last_ip, user_agent) 
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            old_session["user_id"],
                            new_token_hash,
                            old_session["family_id"],
                            new_expires_at,
                            old_session.get("ip_address"),
                            new_ip,
                            new_user_agent,
                        ),
                    )
                    new_session_id = cursor.lastrowid

                    await conn.commit()
                    return new_session_id
        except Exception as e:
            self.logger.error(f"Failed to rotate session: {e}", exc_info=True)
            return None

    async def revoke_session_family(self, family_id: str) -> int:
        """Revoke ALL sessions in a token family (reuse detection response). Returns count."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE sessions 
                        SET revoked = TRUE, revoked_at = CURRENT_TIMESTAMP 
                        WHERE family_id = %s AND revoked = FALSE
                        """,
                        (family_id,),
                    )
                    await conn.commit()
                    return cursor.rowcount
        except Exception as e:
            self.logger.error(f"Failed to revoke session family {family_id}: {e}", exc_info=True)
            return 0

    async def revoke_session(self, session_id: int) -> bool:
        """Revoke a single session by its ID."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        UPDATE sessions 
                        SET revoked = TRUE, revoked_at = CURRENT_TIMESTAMP 
                        WHERE id = %s AND revoked = FALSE
                        """,
                        (session_id,),
                    )
                    await conn.commit()
                    return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"Failed to revoke session {session_id}: {e}", exc_info=True)
            return False

    async def revoke_user_sessions(self, user_id: int) -> None:
        """Revoke all sessions for a user."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "UPDATE sessions SET revoked = TRUE, revoked_at = CURRENT_TIMESTAMP WHERE user_id = %s AND revoked = FALSE",
                        (user_id,),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to revoke sessions: {e}", exc_info=True)
            raise

    async def is_session_active(self, user_id: int, session_id: int) -> bool:
        """Check whether session exists, belongs to user, is not revoked and not expired."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT id
                        FROM sessions
                        WHERE id = %s
                          AND user_id = %s
                          AND revoked = FALSE
                          AND (replaced_by_hash IS NULL OR replaced_by_hash = '')
                          AND expires_at > CURRENT_TIMESTAMP
                        LIMIT 1
                        """,
                        (session_id, user_id),
                    )
                    return await cursor.fetchone() is not None
        except Exception as e:
            self.logger.error(f"Failed to validate session: {e}", exc_info=True)
            return False

    async def get_user_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all active (non-revoked, non-expired) sessions for a user."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        SELECT id, ip_address, last_ip, user_agent, device_label,
                               created_at, expires_at
                        FROM sessions
                        WHERE user_id = %s
                          AND revoked = FALSE
                          AND (replaced_by_hash IS NULL OR replaced_by_hash = '')
                          AND expires_at > CURRENT_TIMESTAMP
                        ORDER BY created_at DESC
                        """,
                        (user_id,),
                    )
                    return await cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Failed to get user sessions: {e}", exc_info=True)
            return []

    async def get_session_owner(self, session_id: int) -> Optional[int]:
        """Get the user_id that owns a given session."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT user_id FROM sessions WHERE id = %s",
                        (session_id,),
                    )
                    row = await cursor.fetchone()
                    return row["user_id"] if row else None
        except Exception as e:
            self.logger.error(f"Failed to get session owner: {e}", exc_info=True)
            return None

    async def log_auth_event(
        self,
        user_id: Optional[int],
        username: str,
        action: str,
        ip: str,
        user_agent: str,
    ) -> None:
        """Log an authentication event."""
        try:
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        """
                        INSERT INTO auth_logs (user_id, username, action, ip_address, user_agent) 
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (user_id, username, action, ip, user_agent),
                    )
                    await conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to log auth event: {e}", exc_info=True)
