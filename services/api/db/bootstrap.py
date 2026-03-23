from __future__ import annotations

from .core import (
    Any,
    COMPLAINT_STATUS_VALUES_SQL,
    Config,
    Dict,
    List,
    MSK,
    Optional,
    SPEC_SESSION_END_REASON_VALUES_SQL,
    WORKFLOW_STATUS_VALUES_SQL,
    _default_role_permissions,
    aiomysql,
    build_dense_permission_map,
    build_dense_service_permission_map,
    date,
    datetime,
    hashlib,
    json,
    normalize_permission_flags,
    time,
    timedelta,
)


class BootstrapMixin:
    async def start(self) -> None:
        """Запуск пула соединений с базой данных и инициализация таблиц."""
        try:
            self.logger.debug(
                f"Initializing connection pool and tables at {self.db_host}..."
            )
            start_time = time.time()

            self.pool = await aiomysql.create_pool(
                host=self.db_host,
                port=self.db_port,
                user=self.db_user,
                password=self.db_password,
                db=self.db_name,
                charset="utf8mb4",
                cursorclass=aiomysql.DictCursor,
                minsize=1,
                maxsize=10,
                pool_recycle=3600,  # Recreate connections every hour to prevent stale connections
                autocommit=True,  # Ensure commits are immediately visible
                init_command="SET SESSION transaction_isolation='READ-COMMITTED', time_zone='+03:00'",  # Prevent stale reads & force MSK
            )

            elapsed = time.time() - start_time
            self.logger.debug(f"✓ Connection pool created in {elapsed:.2f}s")

            await self._init_db()
        except Exception as e:
            self.logger.error(f"Failed to create connection pool: {e}", exc_info=True)
            raise

    async def close(self) -> None:
        """Закрытие пула соединений."""
        try:
            if self.pool:
                self.logger.debug("Closing database connection pool...")
                self.pool.close()
                await self.pool.wait_closed()
                self.logger.info("✓ Database connection pool closed")
        except Exception as e:
            self.logger.error(
                f"Error closing database connection pool: {e}", exc_info=True
            )
        finally:
            self.pool = None

    async def _init_db(self):
        """Initialize the database schema."""
        try:
            self.logger.info("Initializing database schema...")
            async with self.pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SET sql_notes = 0")

                    # =========================================================
                    # 1. Streamers Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS streamers (
                            streamer_id BIGINT UNSIGNED PRIMARY KEY,
                            streamer_name VARCHAR(25) NOT NULL,
                            is_online BOOLEAN DEFAULT FALSE,
                            is_pinned BOOLEAN DEFAULT FALSE,
                            stream_title VARCHAR(255),
                            stream_thumbnail_url VARCHAR(512),
                            profile_image_url VARCHAR(512),
                            stream_game_id BIGINT UNSIGNED,
                            stream_game_name VARCHAR(255),
                            stream_started_at DATETIME NULL,
                            priority INT DEFAULT 0,
                            pr_slots INT DEFAULT 1,
                            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            added_by_id BIGINT UNSIGNED,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            allow_juniors BOOLEAN DEFAULT TRUE,
                            priority_override INT DEFAULT NULL,
                            pr_slots_override INT DEFAULT NULL,
                            UNIQUE(streamer_name),
                            INDEX idx_streamers_online_order (is_online, is_pinned, priority, streamer_name)
                        )
                        """
                    )

                    # =========================================================
                    # 2. Settings Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS settings (
                            id INT PRIMARY KEY DEFAULT 1,
                            notification_channel_id BIGINT UNSIGNED,
                            monitoring_channel_id BIGINT UNSIGNED,
                            monitoring_message_id BIGINT,
                            pr_actions_channel_id BIGINT UNSIGNED,
                            control_panel_channel_id BIGINT UNSIGNED,
                            control_panel_message_id BIGINT UNSIGNED,
                            notification_templates JSON,
                            p0_rate FLOAT DEFAULT 1.0,
                            p1_rate FLOAT DEFAULT 1.2,
                            p2_rate FLOAT DEFAULT 1.5,
                            p3_rate FLOAT DEFAULT 2.0,
                            probation_rate FLOAT DEFAULT 1.2,
                            monitoring_filter_gta BOOLEAN DEFAULT FALSE,
                            site_maintenance_enabled BOOLEAN NOT NULL DEFAULT FALSE
                        )
                        """
                    )

                    # =========================================================
                    # 3. Assistants Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistants (
                            pr_id BIGINT UNSIGNED PRIMARY KEY,
                            nickname VARCHAR(100),
                            role ENUM('junior_employee', 'employee', 'senior_employee', 'manager', 'developer') NOT NULL DEFAULT 'employee',
                            added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            appointed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            dismissed_at DATETIME NULL
                        )
                        """
                    )

                    # =========================================================
                    # 4. Spec Sessions Table
                    # =========================================================
                    await cursor.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS spec_sessions (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            pr_id BIGINT UNSIGNED NOT NULL,
                            
                            target_type ENUM('streamer', 'event', 'manual') NOT NULL DEFAULT 'streamer',
                            target_id BIGINT UNSIGNED NULL,
                            target_name VARCHAR(255) NULL,
                            is_probation BOOLEAN DEFAULT FALSE,
                            
                            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            ended_at DATETIME NULL,
                            end_reason ENUM({SPEC_SESSION_END_REASON_VALUES_SQL}) NULL,
                            
                            # Priority snapshot & override
                            priority_auto TINYINT UNSIGNED NOT NULL DEFAULT 0,
                            priority_override TINYINT UNSIGNED NULL,
                            applied_priority_level TINYINT UNSIGNED GENERATED ALWAYS AS (
                                COALESCE(priority_override, priority_auto)
                            ) STORED,
                            
                            # Rate snapshot & override
                            rate_auto FLOAT NOT NULL DEFAULT 1.00,
                            rate_override FLOAT NULL,
                            applied_hourly_rate FLOAT GENERATED ALWAYS AS (
                                COALESCE(rate_override, rate_auto)
                            ) STORED,
                            
                            # Computed duration
                            duration_seconds INT UNSIGNED GENERATED ALWAYS AS (
                                CASE WHEN ended_at IS NULL THEN NULL
                                     ELSE TIMESTAMPDIFF(SECOND, started_at, ended_at)
                                END
                            ) STORED,
                            
                            # Admin comment if manual spec
                            session_admin_comment VARCHAR(255) NULL,

                            # Persisted contribution to assistant auto points (for deterministic delta recalculation)
                            credited_points FLOAT NOT NULL DEFAULT 0,
                            
                            # Soft-delete
                            deleted_at DATETIME NULL,
                            deleted_by_id BIGINT UNSIGNED NULL,
                            delete_reason VARCHAR(255) NULL,
                            
                            # One active session per PR constraint helper
                            active_pr_id BIGINT UNSIGNED GENERATED ALWAYS AS (
                                CASE WHEN ended_at IS NULL AND deleted_at IS NULL THEN pr_id
                                     ELSE NULL
                                END
                            ) STORED,
                            
                            # Constraints
                            CONSTRAINT chk_ended_after_started CHECK (ended_at IS NULL OR ended_at > started_at),
                            CONSTRAINT chk_manual_no_target CHECK (target_type != 'manual' OR target_id IS NULL),
                            CONSTRAINT chk_non_manual_has_target CHECK (target_type = 'manual' OR target_id IS NOT NULL),
                            CONSTRAINT chk_priority_range CHECK (priority_auto BETWEEN 0 AND 3 AND (priority_override IS NULL OR priority_override BETWEEN 0 AND 3)),
                            CONSTRAINT chk_rate_positive CHECK (rate_auto >= 0 AND (rate_override IS NULL OR rate_override >= 0)),
                            
                            # Indexes
                            UNIQUE INDEX uq_one_active_session_per_pr (active_pr_id),
                            INDEX idx_pr_started (pr_id, started_at),
                            INDEX idx_pr_ended (pr_id, ended_at),
                            INDEX idx_target_started (target_type, target_id, started_at),
                            INDEX idx_target_active (target_type, target_id, ended_at, deleted_at),
                            INDEX idx_pr_active (pr_id, ended_at, deleted_at)
                        )
                        """
                    )

                    # =========================================================
                    # 5. Events Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS events (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            description TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            start_time DATETIME NULL,
                            is_active BOOLEAN DEFAULT TRUE,
                            notification_sent BOOLEAN DEFAULT FALSE,
                            required_pr_count INT DEFAULT 1,
                            priority INT DEFAULT 0,
                            pr_slots INT DEFAULT 1,
                            created_by BIGINT UNSIGNED,
                            is_pinned BOOLEAN DEFAULT FALSE,
                            event_kind ENUM('regular','spec_request') NOT NULL DEFAULT 'regular',
                            approval_status ENUM('approved','pending','rejected') NOT NULL DEFAULT 'approved',
                            requested_by BIGINT UNSIGNED NULL,
                            approved_by BIGINT UNSIGNED NULL,
                            approved_at DATETIME NULL,
                            rejected_by BIGINT UNSIGNED NULL,
                            rejected_at DATETIME NULL,
                            points FLOAT NULL,
                            INDEX idx_events_active_order (is_active, is_pinned, priority, start_time),
                            INDEX idx_events_kind_status_active (event_kind, approval_status, is_active),
                            INDEX idx_events_requested_by_active (requested_by, is_active)
                        )
                        """
                    )
                    
                    # =========================================================
                    # 5.5. Event Participants Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS event_participants (
                            event_id INT UNSIGNED NOT NULL,
                            pr_id BIGINT UNSIGNED NOT NULL,
                            joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (event_id, pr_id),
                            FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
                        )
                        """
                    )

                    # =========================================================
                    # 6. Web Auth Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS web_auth (
                            discord_id BIGINT UNSIGNED PRIMARY KEY,
                            username VARCHAR(50) UNIQUE NOT NULL,
                            password_hash VARCHAR(255) NOT NULL,
                            is_active BOOLEAN DEFAULT TRUE,
                            require_password_change BOOLEAN DEFAULT TRUE,
                            failed_login_attempts INT DEFAULT 0,
                            last_login TIMESTAMP NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_failed_login TIMESTAMP NULL
                        )
                        """
                    )

                    # =========================================================
                    # 7. Sessions Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sessions (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT UNSIGNED NOT NULL, 
                            refresh_token_hash VARCHAR(64) NOT NULL,
                            family_id VARCHAR(32) NOT NULL,
                            replaced_by_hash VARCHAR(64) NULL,
                            expires_at TIMESTAMP NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            revoked BOOLEAN DEFAULT FALSE,
                            revoked_at TIMESTAMP NULL,
                            ip_address VARCHAR(45),
                            last_ip VARCHAR(45) NULL,
                            user_agent TEXT,
                            device_label VARCHAR(128) NULL,
                            INDEX idx_user_id (user_id),
                            INDEX idx_refresh_token_hash (refresh_token_hash),
                            INDEX idx_family_id (family_id)
                        )
                        """
                    )

                    # =========================================================
                    # 8. Auth Logs Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS auth_logs (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT UNSIGNED,
                            username VARCHAR(50),
                            action ENUM('login_success', 'login_failed', 'logout', 'token_refresh', 'password_change') NOT NULL,
                            ip_address VARCHAR(45),
                            user_agent TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_user_id (user_id),
                            INDEX idx_created_at (created_at)
                        )
                        """
                    )

                    # ----------------------------------------------------------
                    # web_auth PK Migration (id -> discord_id), guarded fail-fast
                    # ----------------------------------------------------------
                    await self._migrate_web_auth_pk_to_discord_id(cursor)

                    # =========================================================
                    # 9. Role Permissions Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS role_permissions (
                            role VARCHAR(50) PRIMARY KEY,
                            permissions JSON NOT NULL,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    # =========================================================
                    # 10. Service Principals Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS service_principals (
                            name VARCHAR(100) PRIMARY KEY,
                            token_hash VARCHAR(64) NOT NULL UNIQUE,
                            permissions JSON NOT NULL,
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            INDEX idx_service_token_hash (token_hash)
                        )
                        """
                    )

                    # service_principals hash-only migration, guarded fail-fast
                    await self._migrate_service_principals_hash_only(cursor)

                    # =========================================================
                    # 11. Admin Logs Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS admin_logs (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            action VARCHAR(100) NOT NULL,
                            target_type VARCHAR(50),
                            target_id VARCHAR(100),
                            details JSON NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            actor_name VARCHAR(255) NOT NULL,
                            actor_role VARCHAR(50),
                            INDEX idx_created_at (created_at),
                            INDEX idx_action_created (action, created_at),
                            INDEX idx_actor_created (actor_name, created_at),
                            INDEX idx_target_created (target_type, target_id, created_at)
                        )
                        """
                    )

                    # =========================================================
                    # 11.5. Game Servers Catalog
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS game_servers (
                            id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
                            full_name VARCHAR(255) NOT NULL,
                            short_name VARCHAR(32) NOT NULL,
                            command_name VARCHAR(32) NOT NULL,
                            sort_order SMALLINT UNSIGNED NOT NULL DEFAULT 0,
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            UNIQUE KEY uq_game_servers_full_name (full_name),
                            UNIQUE KEY uq_game_servers_short_name (short_name),
                            UNIQUE KEY uq_game_servers_command_name (command_name),
                            INDEX idx_game_servers_active_sort (is_active, sort_order, id)
                        )
                        """
                    )

                    # =========================================================
                    # 12. Punishment Returns Table
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS punishment_returns (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            punishment_type ENUM('jail', 'mute') NOT NULL,
                            `static` INT UNSIGNED NOT NULL,
                            server TINYINT UNSIGNED NOT NULL,
                            duration INT UNSIGNED NOT NULL,
                            remove_reason ENUM('На стрим', 'На видео') NOT NULL,
                            discord_message_url VARCHAR(512) NULL,
                            removed_by_id BIGINT UNSIGNED NOT NULL,
                            removed_by_name VARCHAR(255) NOT NULL,
                            removed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            claimed_by_id BIGINT UNSIGNED NULL,
                            claimed_by_name VARCHAR(255) NULL,
                            claimed_at TIMESTAMP NULL,
                            completed_by_id BIGINT UNSIGNED NULL,
                            completed_by_name VARCHAR(255) NULL,
                            completed_at TIMESTAMP NULL,
                            status ENUM('pending', 'claimed', 'completed') NOT NULL DEFAULT 'pending',
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            INDEX idx_returns_queue (status, removed_at),
                            INDEX idx_returns_history (completed_at),
                            INDEX idx_returns_static (`static`),
                            INDEX idx_returns_server (server),
                            CONSTRAINT fk_returns_server
                                FOREIGN KEY (server) REFERENCES game_servers (id)
                        )
                        """
                    )

                    # =========================================================
                    # 13. Day-Based Manual Adjustments
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_day_point_adjustments (
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            work_date DATE NOT NULL,
                            delta_points FLOAT NOT NULL DEFAULT 0,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            PRIMARY KEY (assistant_id, work_date),
                            INDEX idx_day_point_adjustments_work_date (work_date)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_day_mchat (
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            work_date DATE NOT NULL,
                            mchat_count INT UNSIGNED NOT NULL DEFAULT 0,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            PRIMARY KEY (assistant_id, work_date),
                            INDEX idx_day_mchat_work_date (work_date)
                        )
                        """
                    )

                    # =========================================================
                    # 14. Weekly Assistant Statistics
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_day_status_overrides (
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            work_date DATE NOT NULL,
                            manual_status ENUM('P', 'U', 'O', 'NONE') NOT NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            updated_by_id BIGINT UNSIGNED NULL,
                            PRIMARY KEY (assistant_id, work_date),
                            INDEX idx_day_status_overrides_work_date (work_date),
                            INDEX idx_day_status_overrides_updated_by (updated_by_id)
                        )
                        """
                    )
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_day_status_overrides
                        MODIFY COLUMN manual_status ENUM('P', 'U', 'O', 'NONE') NOT NULL
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_weekly_reviews (
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            week_start DATE NOT NULL,
                            selected_result ENUM(
                                'Ультра-Актив',
                                'Актив',
                                'Актив/Отпуск',
                                'Инактив',
                                'Инактив/Отпуск',
                                'Отпуск',
                                'Инактив/Актив'
                            ) NULL,
                            payout_type ENUM('EXP', 'Premium', 'MC', 'MONEY') NULL,
                            payout_server_id TINYINT UNSIGNED NULL,
                            payout_static VARCHAR(64) NULL,
                            payout_issue_status ENUM('pending', 'issued') NOT NULL DEFAULT 'pending',
                            payout_issued_at DATETIME NULL,
                            payout_issued_by_id BIGINT UNSIGNED NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            updated_by_id BIGINT UNSIGNED NULL,
                            PRIMARY KEY (assistant_id, week_start),
                            INDEX idx_weekly_reviews_week_start (week_start),
                            INDEX idx_weekly_reviews_updated_by (updated_by_id),
                            INDEX idx_weekly_reviews_payout_server_id (payout_server_id),
                            CONSTRAINT fk_weekly_reviews_payout_server_id
                                FOREIGN KEY (payout_server_id) REFERENCES game_servers (id)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_weekly_payout_type_rules (
                            payout_type ENUM('EXP', 'Premium', 'MC', 'MONEY') PRIMARY KEY,
                            command_name VARCHAR(64) NOT NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_weekly_payout_amount_rules (
                            role_group ENUM('junior', 'default', 'Senior') NOT NULL,
                            payout_type ENUM('EXP', 'Premium', 'MC', 'MONEY') NOT NULL,
                            result_code ENUM('Актив', 'Ультра-Актив') NOT NULL,
                            amount VARCHAR(64) NOT NULL,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            PRIMARY KEY (role_group, payout_type, result_code)
                        )
                        """
                    )

                    # =========================================================
                    # 15. Complaints
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS complaints (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            assistant_id BIGINT UNSIGNED NULL,
                            assistant_name VARCHAR(255) NULL,
                            issuer_id BIGINT UNSIGNED NULL,
                            issuer_name VARCHAR(255) NULL,
                            status ENUM('draft', 'pending', 'issued', 'claimed', 'completed', 'cancelled') NOT NULL DEFAULT 'draft',
                            server TINYINT UNSIGNED NOT NULL,
                            complaint_link VARCHAR(512) NULL,
                            media TEXT NULL,
                            incident_at DATETIME NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            reviewed_at DATETIME NULL,
                            issued_at DATETIME NULL,
                            claimed_at DATETIME NULL,
                            completed_at DATETIME NULL,
                            cancelled_at DATETIME NULL,
                            INDEX idx_complaints_assistant_status (assistant_id, status),
                            INDEX idx_complaints_status_created (status, created_at),
                            INDEX idx_complaints_issued (issued_at),
                            INDEX idx_complaints_completed (completed_at),
                            INDEX idx_complaints_server (server),
                            CONSTRAINT fk_complaints_server
                                FOREIGN KEY (server) REFERENCES game_servers (id)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS complaint_punishments (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            complaint_id BIGINT UNSIGNED NOT NULL,
                            punishment_type ENUM('mute', 'ajail', 'warn', 'ban', 'hardban', 'gunban') NOT NULL,
                            violator_static INT UNSIGNED NOT NULL,
                            duration_value INT UNSIGNED NULL,
                            reason VARCHAR(255) NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            INDEX idx_complaint_punishments_complaint (complaint_id),
                            INDEX idx_complaint_punishments_static (violator_static)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS punishment_removals (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            assistant_name VARCHAR(255) NOT NULL,
                            issuer_id BIGINT UNSIGNED NULL,
                            issuer_name VARCHAR(255) NULL,
                            removal_type ENUM('unjail', 'unmute') NOT NULL,
                            violator_static INT UNSIGNED NOT NULL,
                            server TINYINT UNSIGNED NOT NULL,
                            reason VARCHAR(255) NOT NULL,
                            message_link VARCHAR(512) NULL,
                            status ENUM('draft', 'pending', 'issued') NOT NULL DEFAULT 'draft',
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            reviewed_at DATETIME NULL,
                            issued_at DATETIME NULL,
                            INDEX idx_removals_assistant_status (assistant_id, status),
                            INDEX idx_removals_status_created (status, created_at),
                            INDEX idx_removals_issued (issued_at),
                            INDEX idx_removals_server (server),
                            CONSTRAINT fk_removals_server
                                FOREIGN KEY (server) REFERENCES game_servers (id)
                        )
                        """
                    )

                    # =========================================================
                    # 16. Monthly Sanction Policies
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS monthly_sanction_settings (
                            month_start DATE PRIMARY KEY,
                            check_cycle_size INT UNSIGNED NOT NULL DEFAULT 5,
                            check_immunity_hours_per_day FLOAT NOT NULL DEFAULT 4,
                            point_immunity_hours_per_day FLOAT NOT NULL DEFAULT 5,
                            percent_immunity_hours_per_day FLOAT NOT NULL DEFAULT 6,
                            check_relief_hours_per_day FLOAT NOT NULL DEFAULT 4,
                            point_relief_hours_per_day FLOAT NOT NULL DEFAULT 5,
                            percent_relief_hours_per_day FLOAT NOT NULL DEFAULT 6,
                            check_relief_min_streak_days INT UNSIGNED NOT NULL DEFAULT 2,
                            point_relief_min_streak_days INT UNSIGNED NOT NULL DEFAULT 2,
                            percent_relief_min_streak_days INT UNSIGNED NOT NULL DEFAULT 2,
                            percent_relief_step_amount FLOAT NOT NULL DEFAULT 3,
                            daily_norm_spec FLOAT NOT NULL DEFAULT 4,
                            daily_norm_complaints INT UNSIGNED NOT NULL DEFAULT 0,
                            daily_norm_mchat INT UNSIGNED NOT NULL DEFAULT 0,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS monthly_check_rules (
                            id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            month_start DATE NOT NULL,
                            range_start INT UNSIGNED NOT NULL,
                            range_end INT UNSIGNED NULL,
                            penalty_kind ENUM('point', 'percent', 'oral', 'strict') NOT NULL,
                            penalty_amount FLOAT NOT NULL,
                            INDEX idx_check_rules_month (month_start, range_start, range_end)
                        )
                        """
                    )

                    # =========================================================
                    # 17. Sanction Operations
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sanction_operations (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            operation_date DATE NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            created_by_id BIGINT UNSIGNED NULL,
                            penalty_kind ENUM('check', 'point', 'percent', 'oral', 'strict') NOT NULL,
                            penalty_amount FLOAT NOT NULL,
                            auto_relief_date DATE NULL,
                            recipient_mode ENUM('all_active', 'live_without_active_session', 'selected_only') NOT NULL,
                            status ENUM('queued', 'processing', 'completed', 'cancelled', 'failed') NOT NULL DEFAULT 'queued',
                            processing_mode ENUM('manual_now', 'nightly_auto') NULL,
                            processed_by_id BIGINT UNSIGNED NULL,
                            queued_at DATETIME NULL,
                            processed_at DATETIME NULL,
                            cancelled_at DATETIME NULL,
                            failure_reason TEXT NULL,
                            INDEX idx_sanction_operations_date_status (operation_date, status),
                            INDEX idx_sanction_operations_creator (created_by_id, created_at),
                            INDEX idx_sanction_operations_processed_by (processed_by_id, processed_at)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sanction_operation_members (
                            operation_id BIGINT UNSIGNED NOT NULL,
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            issue_status ENUM('pending', 'issued', 'skipped_immunity', 'skipped_leave', 'failed') NOT NULL DEFAULT 'pending',
                            issue_reason VARCHAR(255) NULL,
                            issued_sanction_id BIGINT UNSIGNED NULL,
                            PRIMARY KEY (operation_id, assistant_id),
                            INDEX idx_operation_members_status (operation_id, issue_status),
                            INDEX idx_operation_members_sanction (issued_sanction_id)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sanction_operation_workoffs (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            operation_id BIGINT UNSIGNED NOT NULL,
                            metric ENUM('spec', 'complaints', 'mchat') NOT NULL,
                            multiplier FLOAT NOT NULL,
                            period_start DATE NOT NULL,
                            period_end DATE NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE KEY uq_operation_workoff_metric (operation_id, metric),
                            INDEX idx_operation_workoffs_period (period_start, period_end)
                        )
                        """
                    )

                    # =========================================================
                    # 18. Sanction Ledger
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_sanctions (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            assistant_id BIGINT UNSIGNED NOT NULL,
                            kind ENUM('check', 'point', 'percent', 'oral', 'strict') NOT NULL,
                            amount_total FLOAT NOT NULL,
                            auto_relief_date DATE NULL,
                            issued_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            source_type ENUM('manual', 'queued_batch', 'check_cycle', 'legacy_migration') NOT NULL,
                            operation_id BIGINT UNSIGNED NULL,
                            basis_date DATE NULL,
                            settings_month DATE NULL,
                            check_rule_hit_no INT UNSIGNED NULL,
                            replaced_by_sanction_id BIGINT UNSIGNED NULL,
                            INDEX idx_assistant_sanctions_assistant_kind (assistant_id, kind, issued_at),
                            INDEX idx_assistant_sanctions_basis_date (basis_date),
                            INDEX idx_assistant_sanctions_settings_month (settings_month),
                            INDEX idx_assistant_sanctions_operation (operation_id)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_sanction_workoffs (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            sanction_id BIGINT UNSIGNED NOT NULL,
                            metric ENUM('spec', 'complaints', 'mchat') NOT NULL,
                            multiplier FLOAT NOT NULL,
                            period_start DATE NOT NULL,
                            period_end DATE NOT NULL,
                            target_amount FLOAT NOT NULL,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE KEY uq_assistant_sanction_workoff_metric (sanction_id, metric),
                            INDEX idx_assistant_sanction_workoffs_period (period_start, period_end)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS assistant_sanction_reliefs (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            sanction_id BIGINT UNSIGNED NOT NULL,
                            amount FLOAT NOT NULL,
                            relieved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            basis_date DATE NULL,
                            relief_type ENUM('default', 'custom_workoff', 'cycle_reset', 'month_reset', 'manual', 'replacement', 'auto_expire') NOT NULL,
                            INDEX idx_assistant_sanction_reliefs_sanction (sanction_id, relieved_at),
                            INDEX idx_assistant_sanction_reliefs_basis (basis_date, relief_type)
                        )
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sanction_nightly_runs (
                            basis_date DATE PRIMARY KEY,
                            status ENUM('processing', 'completed', 'failed') NOT NULL,
                            started_at DATETIME NOT NULL,
                            finished_at DATETIME NULL,
                            failure_reason TEXT NULL,
                            INDEX idx_sanction_nightly_runs_status (status, started_at)
                        )
                        """
                    )

                    # =========================================================
                    # 19. Integration Delivery Outbox
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS broker_outbox (
                            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                            routing_key VARCHAR(255) NOT NULL,
                            payload JSON NOT NULL,
                            status ENUM('pending', 'processing', 'sent') NOT NULL DEFAULT 'pending',
                            attempts INT UNSIGNED NOT NULL DEFAULT 0,
                            available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            processing_started_at DATETIME NULL,
                            sent_at DATETIME NULL,
                            last_error TEXT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_broker_outbox_delivery (status, available_at, id),
                            INDEX idx_broker_outbox_created (created_at)
                        )
                        """
                    )

                    # =========================================================
                    # VIEWS (Requires multiple tables)
                    # =========================================================
                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW active_assignments_v AS
                        SELECT
                            ss.id AS session_id,
                            ss.pr_id,
                            ss.target_type,
                            ss.target_id,
                            CASE
                                WHEN ss.target_name IS NOT NULL THEN ss.target_name
                                WHEN ss.target_type = 'streamer' THEN s.streamer_name
                                WHEN ss.target_type = 'event' THEN e.name
                                ELSE NULL
                            END AS target_name,
                            ss.is_probation,
                            ss.started_at,
                            e.event_kind,
                            e.approval_status
                        FROM spec_sessions ss
                        LEFT JOIN streamers s
                            ON ss.target_type = 'streamer'
                            AND ss.target_id = s.streamer_id
                        LEFT JOIN events e
                            ON ss.target_type = 'event'
                            AND ss.target_id = e.id
                        WHERE ss.ended_at IS NULL
                          AND ss.deleted_at IS NULL
                        """
                    )

                    # Day-Slicing View (Recursive CTE)
                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW spec_session_day_slices AS
                        WITH RECURSIVE eligible_sessions AS (
                            SELECT
                                ss.id AS session_id,
                                ss.pr_id,
                                ss.target_type,
                                ss.target_id,
                                ss.is_probation,
                                ss.applied_priority_level,
                                ss.applied_hourly_rate,
                                CASE
                                    WHEN ss.target_type = 'event'
                                         AND e.event_kind = 'spec_request'
                                         AND e.approval_status = 'approved'
                                    THEN GREATEST(
                                        ss.started_at,
                                        COALESCE(e.approved_at, ss.started_at)
                                    )
                                    ELSE ss.started_at
                                END AS effective_started_at,
                                ss.ended_at
                            FROM spec_sessions ss
                            LEFT JOIN events e
                              ON ss.target_type = 'event'
                             AND e.id = ss.target_id
                            WHERE ss.ended_at IS NOT NULL
                              AND ss.deleted_at IS NULL
                              AND (
                                  ss.target_type <> 'event'
                                  OR e.event_kind <> 'spec_request'
                                  OR e.approval_status = 'approved'
                              )
                        ),
                        day_slices AS (
                            # Anchor: start of each completed, non-deleted session
                            SELECT
                                es.session_id,
                                es.pr_id,
                                es.target_type,
                                es.target_id,
                                es.is_probation,
                                es.applied_priority_level,
                                es.applied_hourly_rate,
                                es.effective_started_at AS started_at,
                                es.ended_at,
                                # slice_start = effective_started_at for the first day
                                es.effective_started_at AS slice_start,
                                # slice_end = midnight of the next day, or ended_at (whichever is earlier)
                                LEAST(
                                    DATE_ADD(DATE(es.effective_started_at), INTERVAL 1 DAY),
                                    es.ended_at
                                ) AS slice_end
                            FROM eligible_sessions es
                            WHERE es.effective_started_at < es.ended_at
                            
                            UNION ALL
                            
                            # Recursive: next day slices
                            SELECT
                                ds.session_id,
                                ds.pr_id,
                                ds.target_type,
                                ds.target_id,
                                ds.is_probation,
                                ds.applied_priority_level,
                                ds.applied_hourly_rate,
                                ds.started_at,
                                ds.ended_at,
                                ds.slice_end AS slice_start,
                                LEAST(
                                    DATE_ADD(DATE(ds.slice_end), INTERVAL 1 DAY),
                                    ds.ended_at
                                ) AS slice_end
                            FROM day_slices ds
                            WHERE ds.slice_end < ds.ended_at
                        )
                        SELECT
                            session_id,
                            pr_id,
                            target_type,
                            target_id,
                            is_probation,
                            applied_priority_level,
                            applied_hourly_rate,
                            DATE(slice_start) AS work_date,
                            TIMESTAMPDIFF(SECOND, slice_start, slice_end) AS seconds_in_day,
                            ROUND(
                                (TIMESTAMPDIFF(SECOND, slice_start, slice_end) / 3600.0) * applied_hourly_rate,
                                4
                            ) AS points_in_day
                        FROM day_slices
                        """
                    )

                    # Aggregated Daily Stats View
                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW daily_stats AS
                        SELECT
                            pr_id,
                            work_date AS date,
                            SUM(CASE WHEN applied_priority_level = 0 AND 0 = is_probation THEN seconds_in_day ELSE 0 END) AS p0_seconds,
                            SUM(CASE WHEN applied_priority_level = 1 AND 0 = is_probation THEN seconds_in_day ELSE 0 END) AS p1_seconds,
                            SUM(CASE WHEN applied_priority_level = 2 AND 0 = is_probation THEN seconds_in_day ELSE 0 END) AS p2_seconds,
                            SUM(CASE WHEN applied_priority_level = 3 AND 0 = is_probation THEN seconds_in_day ELSE 0 END) AS p3_seconds,
                            SUM(CASE WHEN is_probation THEN seconds_in_day ELSE 0 END) AS probation_seconds,
                            SUM(points_in_day) AS total_points
                        FROM spec_session_day_slices
                        GROUP BY pr_id, work_date
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW assistant_day_spec_totals AS
                        SELECT
                            pr_id AS assistant_id,
                            work_date,
                            SUM(seconds_in_day) AS spec_seconds_on_day,
                            ROUND(SUM(seconds_in_day) / 3600.0, 4) AS spec_hours_on_day,
                            ROUND(SUM(points_in_day), 4) AS spec_points_auto
                        FROM spec_session_day_slices
                        GROUP BY pr_id, work_date
                        """
                    )

                    await cursor.execute(
                        """
                        CREATE OR REPLACE VIEW sanction_balances AS
                        SELECT
                            s.id AS sanction_id,
                            s.assistant_id,
                            s.kind,
                            s.amount_total,
                            s.auto_relief_date,
                            s.issued_at,
                            s.source_type,
                            s.operation_id AS source_batch_id,
                            s.basis_date,
                            s.settings_month AS policy_month,
                            s.check_rule_hit_no AS cycle_no,
                            ROUND(COALESCE(SUM(sr.amount), 0), 4) AS relieved_amount,
                            GREATEST(ROUND(s.amount_total - COALESCE(SUM(sr.amount), 0), 4), 0) AS active_amount
                        FROM assistant_sanctions s
                        LEFT JOIN assistant_sanction_reliefs sr ON sr.sanction_id = s.id
                        GROUP BY
                            s.id,
                            s.assistant_id,
                            s.kind,
                            s.amount_total,
                            s.auto_relief_date,
                            s.issued_at,
                            s.source_type,
                            s.operation_id,
                            s.basis_date,
                            s.settings_month,
                            s.check_rule_hit_no
                        """
                    )

                    await cursor.execute("SET sql_notes = 1")
                    await conn.commit()

                    await self._init_default_permissions(conn)
                    await self._init_game_servers(conn)
                    await self._init_weekly_payout_config(conn)
                    await self._init_default_service_principals(conn)
                    await self._ensure_singleton_settings(conn)
                    await self._init_cutover_schema(conn)

                    self.logger.info("Database schema initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize database: {e}", exc_info=True)
            raise

    async def _init_cutover_schema(self, conn) -> None:
        """Idempotent additive migration path for the assistant_sanctions/workoff cutover."""
        async with conn.cursor() as cursor:
            try:
                await cursor.execute(
                    "ALTER TABLE settings MODIFY COLUMN monitoring_message_id BIGINT UNSIGNED"
                )
            except Exception:
                pass

            table_renames = [
                ("monthly_sanction_settings", "monthly_sanction_settings"),
                ("monthly_check_rules", "monthly_check_rules"),
                ("sanction_operations", "sanction_operations"),
                ("sanction_operation_members", "sanction_operation_members"),
                ("sanction_operation_workoffs", "sanction_operation_workoffs"),
                ("assistant_sanctions", "assistant_sanctions"),
                ("assistant_sanction_workoffs", "assistant_sanction_workoffs"),
                ("assistant_sanction_reliefs", "assistant_sanction_reliefs"),
                ("sanction_nightly_runs", "sanction_nightly_runs"),
            ]
            for old_name, new_name in table_renames:
                if await self._table_exists(cursor, old_name) and not await self._table_exists(cursor, new_name):
                    await cursor.execute(f"RENAME TABLE {old_name} TO {new_name}")

            column_renames = [
                ("monthly_check_rules", "cycle_from", "range_start", "INT UNSIGNED NOT NULL"),
                ("monthly_check_rules", "cycle_to", "range_end", "INT UNSIGNED NULL"),
                ("monthly_check_rules", "sanction_kind", "penalty_kind", "ENUM('point', 'percent', 'oral', 'strict') NOT NULL"),
                ("monthly_check_rules", "sanction_amount", "penalty_amount", "FLOAT NOT NULL"),
                ("sanction_operations", "basis_date", "operation_date", "DATE NOT NULL"),
                ("sanction_operations", "sanction_kind", "penalty_kind", "ENUM('check', 'point', 'percent', 'oral', 'strict') NOT NULL"),
                ("sanction_operations", "sanction_amount", "penalty_amount", "FLOAT NOT NULL"),
                ("sanction_operations", "audience_mode", "recipient_mode", "ENUM('all_active', 'live_without_active_session', 'selected_only') NOT NULL"),
                ("sanction_operation_members", "batch_id", "operation_id", "BIGINT UNSIGNED NOT NULL"),
                ("sanction_operation_members", "execution_status", "issue_status", "ENUM('pending', 'issued', 'skipped_immunity', 'skipped_leave', 'failed') NOT NULL DEFAULT 'pending'"),
                ("sanction_operation_members", "execution_reason", "issue_reason", "VARCHAR(255) NULL"),
                ("sanction_operation_workoffs", "batch_id", "operation_id", "BIGINT UNSIGNED NOT NULL"),
                ("assistant_sanctions", "source_batch_id", "operation_id", "BIGINT UNSIGNED NULL"),
                ("assistant_sanctions", "policy_month", "settings_month", "DATE NULL"),
                ("assistant_sanctions", "cycle_no", "check_rule_hit_no", "INT UNSIGNED NULL"),
            ]
            for table_name, old_column, new_column, column_def in column_renames:
                if await self._table_exists(cursor, table_name) and await self._column_exists(cursor, table_name, old_column) and not await self._column_exists(cursor, table_name, new_column):
                    await cursor.execute(
                        f"ALTER TABLE {table_name} CHANGE COLUMN {old_column} {new_column} {column_def}"
                    )

            if await self._table_exists(cursor, "monthly_check_rules") and await self._column_exists(cursor, "monthly_check_rules", "range_end"):
                await cursor.execute(
                    "ALTER TABLE monthly_check_rules MODIFY COLUMN range_end INT UNSIGNED NULL"
                )
                await cursor.execute(
                    """
                    UPDATE monthly_check_rules current_rule
                    LEFT JOIN monthly_check_rules other_rule
                      ON other_rule.month_start = current_rule.month_start
                     AND other_rule.id <> current_rule.id
                     AND (
                         other_rule.range_start > current_rule.range_end
                         OR other_rule.range_end IS NULL
                     )
                    SET current_rule.range_end = NULL
                    WHERE current_rule.range_start = 8
                      AND current_rule.range_end = 8
                      AND current_rule.penalty_kind = 'strict'
                      AND other_rule.id IS NULL
                    """
                )

            if await self._table_exists(cursor, "sanction_operations"):
                if not await self._column_exists(cursor, "sanction_operations", "auto_relief_date"):
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        ADD COLUMN auto_relief_date DATE NULL
                        AFTER penalty_amount
                        """
                    )
                if not await self._column_exists(cursor, "sanction_operations", "processing_mode"):
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        ADD COLUMN processing_mode ENUM('manual_now', 'nightly_auto') NULL
                        AFTER status
                        """
                    )

            if not await self._table_exists(cursor, "broker_outbox"):
                await cursor.execute(
                    """
                    CREATE TABLE broker_outbox (
                        id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
                        routing_key VARCHAR(255) NOT NULL,
                        payload JSON NOT NULL,
                        status ENUM('pending', 'processing', 'sent') NOT NULL DEFAULT 'pending',
                        attempts INT UNSIGNED NOT NULL DEFAULT 0,
                        available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        processing_started_at DATETIME NULL,
                        sent_at DATETIME NULL,
                        last_error TEXT NULL,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_broker_outbox_delivery (status, available_at, id),
                        INDEX idx_broker_outbox_created (created_at)
                    )
                    """
                )

            if not await self._table_exists(cursor, "sanction_nightly_runs"):
                await cursor.execute(
                    """
                    CREATE TABLE sanction_nightly_runs (
                        basis_date DATE PRIMARY KEY,
                        status ENUM('processing', 'completed', 'failed') NOT NULL,
                        started_at DATETIME NOT NULL,
                        finished_at DATETIME NULL,
                        failure_reason TEXT NULL,
                        INDEX idx_sanction_nightly_runs_status (status, started_at)
                    )
                    """
                )

            if await self._table_exists(cursor, "sanction_operations"):
                if not await self._column_exists(cursor, "sanction_operations", "processed_by_id"):
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        ADD COLUMN processed_by_id BIGINT UNSIGNED NULL
                        AFTER processing_mode
                        """
                    )
                if not await self._index_exists(cursor, "sanction_operations", "idx_sanction_operations_processed_by"):
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        ADD INDEX idx_sanction_operations_processed_by (processed_by_id, processed_at)
                        """
                    )
                if await self._column_exists(cursor, "sanction_operations", "audience_mode"):
                    await cursor.execute(
                        """
                        UPDATE sanction_operations
                        SET audience_mode = 'selected_only'
                        WHERE audience_mode = 'all_except'
                        """
                    )
                elif await self._column_exists(cursor, "sanction_operations", "recipient_mode"):
                    try:
                        await cursor.execute(
                            """
                            UPDATE sanction_operations
                            SET recipient_mode = 'selected_only'
                            WHERE recipient_mode = 'all_except'
                            """
                        )
                    except Exception:
                        pass
                try:
                    await cursor.execute(
                        """
                        UPDATE sanction_operations
                        SET status = 'queued',
                            queued_at = COALESCE(queued_at, created_at, CURRENT_TIMESTAMP)
                        WHERE status = 'draft'
                        """
                    )
                except Exception:
                    pass
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operations
                        MODIFY COLUMN status ENUM('queued', 'processing', 'completed', 'cancelled', 'failed') NOT NULL DEFAULT 'queued'
                        """
                    )
                except Exception:
                    pass

            if not await self._column_exists(cursor, "assistants", "dismissed_at"):
                await cursor.execute(
                    "ALTER TABLE assistants ADD COLUMN dismissed_at DATETIME NULL AFTER updated_at"
                )

            if await self._table_exists(cursor, "assistant_sanctions"):
                if not await self._column_exists(cursor, "assistant_sanctions", "auto_relief_date"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_sanctions
                        ADD COLUMN auto_relief_date DATE NULL
                        AFTER amount_total
                        """
                    )

            if await self._table_exists(cursor, "assistant_sanction_reliefs"):
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_sanction_reliefs
                        MODIFY COLUMN relief_type ENUM(
                            'default',
                            'custom_workoff',
                            'cycle_reset',
                            'month_reset',
                            'manual',
                            'replacement',
                            'auto_expire'
                        ) NOT NULL
                        """
                    )
                except Exception:
                    pass

            if await self._table_exists(cursor, "sanction_operation_members"):
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE sanction_operation_members
                        MODIFY COLUMN issue_status ENUM(
                            'pending',
                            'issued',
                            'skipped_immunity',
                            'skipped_leave',
                            'failed'
                        ) NOT NULL DEFAULT 'pending'
                        """
                    )
                except Exception:
                    pass

            if await self._table_exists(cursor, "spec_sessions") and await self._column_exists(
                cursor, "spec_sessions", "end_reason"
            ):
                await cursor.execute(
                    f"""
                    ALTER TABLE spec_sessions
                    MODIFY COLUMN end_reason ENUM({SPEC_SESSION_END_REASON_VALUES_SQL}) NULL
                    """
                )

            if not await self._column_exists(cursor, "admin_logs", "actor_id"):
                await cursor.execute(
                    "ALTER TABLE admin_logs ADD COLUMN actor_id BIGINT UNSIGNED NULL AFTER actor_role"
                )
            if not await self._column_exists(cursor, "admin_logs", "actor_type"):
                await cursor.execute(
                    "ALTER TABLE admin_logs ADD COLUMN actor_type VARCHAR(32) NULL AFTER actor_id"
                )
            if not await self._column_exists(cursor, "admin_logs", "trace_id"):
                await cursor.execute(
                    "ALTER TABLE admin_logs ADD COLUMN trace_id VARCHAR(64) NULL AFTER actor_type"
                )
            if await self._table_exists(cursor, "game_servers"):
                await self._seed_game_servers(cursor)
            else:
                await cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS game_servers (
                        id TINYINT UNSIGNED NOT NULL PRIMARY KEY,
                        full_name VARCHAR(255) NOT NULL,
                        short_name VARCHAR(32) NOT NULL,
                        command_name VARCHAR(32) NOT NULL,
                        sort_order SMALLINT UNSIGNED NOT NULL DEFAULT 0,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_game_servers_full_name (full_name),
                        UNIQUE KEY uq_game_servers_short_name (short_name),
                        UNIQUE KEY uq_game_servers_command_name (command_name),
                        INDEX idx_game_servers_active_sort (is_active, sort_order, id)
                    )
                    """
                )
                await self._seed_game_servers(cursor)
            if await self._table_exists(cursor, "assistant_weekly_reviews"):
                if not await self._column_exists(cursor, "assistant_weekly_reviews", "payout_issue_status"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_weekly_reviews
                        ADD COLUMN payout_issue_status ENUM('pending', 'issued') NOT NULL DEFAULT 'pending'
                        AFTER payout_static
                        """
                    )
                if not await self._column_exists(cursor, "assistant_weekly_reviews", "payout_issued_at"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_weekly_reviews
                        ADD COLUMN payout_issued_at DATETIME NULL
                        AFTER payout_issue_status
                        """
                    )
                if not await self._column_exists(cursor, "assistant_weekly_reviews", "payout_issued_by_id"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_weekly_reviews
                        ADD COLUMN payout_issued_by_id BIGINT UNSIGNED NULL
                        AFTER payout_issued_at
                        """
                    )
                if not await self._column_exists(cursor, "assistant_weekly_reviews", "payout_server_id"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_weekly_reviews
                        ADD COLUMN payout_server_id TINYINT UNSIGNED NULL
                        AFTER payout_type
                        """
                    )
                if not await self._index_exists(
                    cursor,
                    "assistant_weekly_reviews",
                    "idx_weekly_reviews_payout_server_id",
                ):
                    try:
                        await cursor.execute(
                            "CREATE INDEX idx_weekly_reviews_payout_server_id ON assistant_weekly_reviews (payout_server_id)"
                        )
                    except Exception:
                        pass
                await cursor.execute(
                    """
                    ALTER TABLE assistant_weekly_reviews
                    MODIFY COLUMN payout_issue_status ENUM('pending', 'issued') NOT NULL DEFAULT 'pending'
                    """
                )
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_weekly_reviews
                        ADD CONSTRAINT fk_weekly_reviews_payout_server_id
                        FOREIGN KEY (payout_server_id) REFERENCES game_servers (id)
                        """
                    )
                except Exception:
                    pass
                if await self._column_exists(cursor, "assistant_weekly_reviews", "payout_server"):
                    await cursor.execute(
                        """
                        ALTER TABLE assistant_weekly_reviews
                        DROP COLUMN payout_server
                        """
                    )
            if await self._table_exists(cursor, "assistant_weekly_payout_servers"):
                await cursor.execute("DROP TABLE assistant_weekly_payout_servers")
            if await self._table_exists(cursor, "settings") and not await self._column_exists(
                cursor, "settings", "site_maintenance_enabled"
            ):
                await cursor.execute(
                    """
                    ALTER TABLE settings
                    ADD COLUMN site_maintenance_enabled BOOLEAN NOT NULL DEFAULT FALSE
                    AFTER monitoring_filter_gta
                    """
                )
            if await self._table_exists(cursor, "complaints"):
                if not await self._column_exists(cursor, "complaints", "assistant_name"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN assistant_name VARCHAR(255) NULL AFTER assistant_id"
                    )
                if not await self._column_exists(cursor, "complaints", "issuer_id"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN issuer_id BIGINT UNSIGNED NULL AFTER assistant_name"
                    )
                if not await self._column_exists(cursor, "complaints", "issuer_name"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN issuer_name VARCHAR(255) NULL AFTER issuer_id"
                    )
                if not await self._column_exists(cursor, "complaints", "server"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN server TINYINT UNSIGNED NOT NULL AFTER status"
                    )
                if not await self._column_exists(cursor, "complaints", "complaint_link"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN complaint_link VARCHAR(512) NULL AFTER server"
                    )
                if not await self._column_exists(cursor, "complaints", "media"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN media TEXT NULL AFTER complaint_link"
                    )
                if not await self._column_exists(cursor, "complaints", "incident_at"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN incident_at DATETIME NULL AFTER media"
                    )
                if not await self._column_exists(cursor, "complaints", "updated_at"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at"
                    )
                if not await self._column_exists(cursor, "complaints", "reviewed_at"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN reviewed_at DATETIME NULL AFTER updated_at"
                    )
                if not await self._column_exists(cursor, "complaints", "issued_at"):
                    await cursor.execute(
                        "ALTER TABLE complaints ADD COLUMN issued_at DATETIME NULL AFTER reviewed_at"
                    )
                if not await self._index_exists(cursor, "complaints", "idx_complaints_server"):
                    try:
                        await cursor.execute(
                            "CREATE INDEX idx_complaints_server ON complaints (server)"
                        )
                    except Exception:
                        pass
                await cursor.execute(
                    f"""
                    ALTER TABLE complaints
                    MODIFY COLUMN status ENUM({COMPLAINT_STATUS_VALUES_SQL}) NOT NULL DEFAULT 'draft'
                    """
                )
                await cursor.execute(
                    """
                    ALTER TABLE complaints
                    MODIFY COLUMN server TINYINT UNSIGNED NOT NULL
                    """
                )
                try:
                    await cursor.execute(
                        "CREATE INDEX idx_complaints_status_created ON complaints (status, created_at)"
                    )
                except Exception:
                    pass
                try:
                    await cursor.execute(
                        "CREATE INDEX idx_complaints_issued ON complaints (issued_at)"
                    )
                except Exception:
                    pass
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE complaints
                        ADD CONSTRAINT fk_complaints_server
                        FOREIGN KEY (server) REFERENCES game_servers (id)
                        """
                    )
                except Exception:
                    pass
            if await self._table_exists(cursor, "punishment_removals"):
                if not await self._index_exists(cursor, "punishment_removals", "idx_removals_server"):
                    try:
                        await cursor.execute(
                            "CREATE INDEX idx_removals_server ON punishment_removals (server)"
                        )
                    except Exception:
                        pass
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE punishment_removals
                        ADD CONSTRAINT fk_removals_server
                        FOREIGN KEY (server) REFERENCES game_servers (id)
                        """
                    )
                except Exception:
                    pass
                await cursor.execute(
                    f"""
                    ALTER TABLE punishment_removals
                    MODIFY COLUMN status ENUM({WORKFLOW_STATUS_VALUES_SQL}) NOT NULL DEFAULT 'draft'
                    """
                )
            if await self._table_exists(cursor, "punishment_returns"):
                try:
                    await cursor.execute(
                        """
                        ALTER TABLE punishment_returns
                        ADD CONSTRAINT fk_returns_server
                        FOREIGN KEY (server) REFERENCES game_servers (id)
                        """
                    )
                except Exception:
                    pass
            await self._seed_default_monthly_policies(cursor)
            await self._backfill_legacy_balances(cursor)
            await self._drop_legacy_assistant_balance_columns(cursor)
            await conn.commit()

    async def _seed_default_monthly_policies(self, cursor) -> None:
        """Ensure previous/current/next month policy defaults exist."""
        current_msk = datetime.now(MSK).date()
        month_starts = {
            self._month_start_for(current_msk),
            self._month_start_for((current_msk.replace(day=1) - timedelta(days=1))),
            self._month_start_for((current_msk.replace(day=28) + timedelta(days=4)).replace(day=1)),
        }
        default_rules = [
            (1, 2, "point", 1.0),
            (3, 3, "point", 2.0),
            (4, 5, "percent", 3.0),
            (6, 6, "percent", 5.0),
            (7, 7, "oral", 1.0),
            (8, None, "strict", 1.0),
        ]

        for month_start in sorted(month_starts):
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
                "SELECT COUNT(*) AS cnt FROM monthly_check_rules WHERE month_start = %s",
                (month_start,),
            )
            row = await cursor.fetchone() or {}
            if int(row.get("cnt", 0)) == 0:
                for range_start, range_end, penalty_kind, penalty_amount in default_rules:
                    await cursor.execute(
                        """
                        INSERT INTO monthly_check_rules (
                            month_start, range_start, range_end, penalty_kind, penalty_amount
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (month_start, range_start, range_end, penalty_kind, penalty_amount),
                    )

    async def _backfill_legacy_balances(self, cursor) -> None:
        """One-time cutover of legacy stored balances into the new ledger/day tables."""
        if not await self._table_exists(cursor, "assistants"):
            return

        has_manual_adjustment = await self._column_exists(
            cursor, "assistants", "manual_points_adjustment"
        )
        has_penalty_points = await self._column_exists(
            cursor, "assistants", "penalty_points"
        )
        has_penalty_percent = await self._column_exists(
            cursor, "assistants", "penalty_percent"
        )
        has_warnings_units = await self._column_exists(
            cursor, "assistants", "warnings_units"
        )

        # Manual points -> opening day adjustments on appointed/added date.
        if has_manual_adjustment:
            await cursor.execute(
                """
                INSERT INTO assistant_day_point_adjustments (assistant_id, work_date, delta_points)
                SELECT
                    a.pr_id,
                    COALESCE(DATE(a.appointed_at), DATE(a.added_at), CURDATE()) AS work_date,
                    ROUND(a.manual_points_adjustment, 4)
                FROM assistants a
                WHERE COALESCE(a.manual_points_adjustment, 0) <> 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_day_point_adjustments ad
                      WHERE ad.assistant_id = a.pr_id
                        AND ad.work_date = COALESCE(DATE(a.appointed_at), DATE(a.added_at), CURDATE())
                  )
                """
            )
            await cursor.execute(
                """
                UPDATE assistants
                SET manual_points_adjustment = 0
                WHERE COALESCE(manual_points_adjustment, 0) <> 0
                """
            )

        # Stored assistant_sanctions -> opening ledger rows.
        if has_penalty_points:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (assistant_id, kind, amount_total, issued_at, source_type, basis_date, settings_month)
                SELECT
                    a.pr_id,
                    'point',
                    ROUND(a.penalty_points, 4),
                    CURRENT_TIMESTAMP,
                    'legacy_migration',
                    CURDATE(),
                    DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
                FROM assistants a
                WHERE COALESCE(a.penalty_points, 0) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_sanctions s
                      WHERE s.assistant_id = a.pr_id
                        AND s.kind = 'point'
                        AND s.source_type = 'legacy_migration'
                  )
                """
            )

        if has_penalty_percent:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (assistant_id, kind, amount_total, issued_at, source_type, basis_date, settings_month)
                SELECT
                    a.pr_id,
                    'percent',
                    ROUND(a.penalty_percent, 4),
                    CURRENT_TIMESTAMP,
                    'legacy_migration',
                    CURDATE(),
                    DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
                FROM assistants a
                WHERE COALESCE(a.penalty_percent, 0) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_sanctions s
                      WHERE s.assistant_id = a.pr_id
                        AND s.kind = 'percent'
                        AND s.source_type = 'legacy_migration'
                  )
                """
            )

        if has_warnings_units:
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (assistant_id, kind, amount_total, issued_at, source_type, basis_date, settings_month)
                SELECT
                    a.pr_id,
                    'strict',
                    FLOOR(COALESCE(a.warnings_units, 0) / 2),
                    CURRENT_TIMESTAMP,
                    'legacy_migration',
                    CURDATE(),
                    DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
                FROM assistants a
                WHERE FLOOR(COALESCE(a.warnings_units, 0) / 2) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_sanctions s
                      WHERE s.assistant_id = a.pr_id
                        AND s.kind = 'strict'
                        AND s.source_type = 'legacy_migration'
                  )
                """
            )
            await cursor.execute(
                """
                INSERT INTO assistant_sanctions (assistant_id, kind, amount_total, issued_at, source_type, basis_date, settings_month)
                SELECT
                    a.pr_id,
                    'oral',
                    MOD(COALESCE(a.warnings_units, 0), 2),
                    CURRENT_TIMESTAMP,
                    'legacy_migration',
                    CURDATE(),
                    DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
                FROM assistants a
                WHERE MOD(COALESCE(a.warnings_units, 0), 2) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM assistant_sanctions s
                      WHERE s.assistant_id = a.pr_id
                        AND s.kind = 'oral'
                        AND s.source_type = 'legacy_migration'
                  )
                """
            )

        if has_penalty_points or has_penalty_percent or has_warnings_units:
            set_parts: list[str] = []
            where_parts: list[str] = []
            if has_penalty_points:
                set_parts.append("penalty_points = 0")
                where_parts.append("COALESCE(penalty_points, 0) <> 0")
            if has_penalty_percent:
                set_parts.append("penalty_percent = 0")
                where_parts.append("COALESCE(penalty_percent, 0) <> 0")
            if has_warnings_units:
                set_parts.append("warnings_units = 0")
                where_parts.append("COALESCE(warnings_units, 0) <> 0")
            if set_parts and where_parts:
                await cursor.execute(
                    f"""
                    UPDATE assistants
                    SET {", ".join(set_parts)}
                    WHERE {" OR ".join(where_parts)}
                    """
                )

    async def _drop_legacy_assistant_balance_columns(self, cursor) -> None:
        """Drop legacy mutable balance cache columns after cutover backfill."""
        if not await self._table_exists(cursor, "assistants"):
            return

        legacy_columns = [
            "total_points",
            "auto_points_total",
            "manual_points_adjustment",
            "penalty_points",
            "penalty_percent",
            "warnings_units",
        ]
        for column_name in legacy_columns:
            if not await self._column_exists(cursor, "assistants", column_name):
                continue
            try:
                await cursor.execute(f"ALTER TABLE assistants DROP COLUMN {column_name}")
                self.logger.info("Dropped legacy assistants.%s column", column_name)
            except Exception as exc:
                # Keep startup idempotent for mixed MariaDB/MySQL deployments.
                self.logger.warning(
                    "Could not drop legacy assistants.%s column: %s",
                    column_name,
                    exc,
                )

    async def _migrate_web_auth_pk_to_discord_id(self, cursor) -> None:
        """
        Guarded migration for legacy web_auth(id PK) -> web_auth(discord_id PK).

        The sequence is intentionally fail-fast to avoid partial boot with broken auth.
        """
        if not await self._table_exists(cursor, "web_auth"):
            return

        has_id = await self._column_exists(cursor, "web_auth", "id")
        has_discord_id = await self._column_exists(cursor, "web_auth", "discord_id")
        if not has_discord_id:
            raise RuntimeError(
                "web_auth migration precondition failed: column 'discord_id' is missing. "
                "Manual intervention required."
            )

        # Always normalize dependent column types for modern IDs.
        await cursor.execute("ALTER TABLE sessions MODIFY COLUMN user_id BIGINT UNSIGNED NOT NULL")
        await cursor.execute("ALTER TABLE auth_logs MODIFY COLUMN user_id BIGINT UNSIGNED")

        if not has_id:
            return

        await cursor.execute("SELECT COUNT(*) AS cnt FROM web_auth WHERE discord_id IS NULL")
        row = await cursor.fetchone() or {}
        if int(row.get("cnt", 0)) > 0:
            raise RuntimeError(
                "web_auth migration precondition failed: NULL discord_id found. "
                "Manual intervention required."
            )

        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM (
                SELECT discord_id
                FROM web_auth
                GROUP BY discord_id
                HAVING COUNT(*) > 1
            ) AS dup
            """
        )
        dup_row = await cursor.fetchone() or {}
        if int(dup_row.get("cnt", 0)) > 0:
            raise RuntimeError(
                "web_auth migration precondition failed: duplicate discord_id values detected. "
                "Manual intervention required."
            )

        self.logger.info("Starting guarded web_auth PK migration (id -> discord_id)...")

        # Rewrite FK-like references before dropping legacy key.
        await cursor.execute(
            "UPDATE sessions s JOIN web_auth w ON s.user_id = w.id SET s.user_id = w.discord_id"
        )
        await cursor.execute(
            "UPDATE auth_logs l JOIN web_auth w ON l.user_id = w.id SET l.user_id = w.discord_id"
        )

        pk_cols = await self._get_primary_key_columns(cursor, "web_auth")
        if pk_cols not in ([], ["id"], ["discord_id"]):
            raise RuntimeError(
                f"web_auth migration precondition failed: unexpected PK shape {pk_cols}. "
                "Manual intervention required."
            )

        if await self._column_is_auto_increment(cursor, "web_auth", "id"):
            if not await self._index_exists(cursor, "web_auth", "uq_web_auth_id_tmp"):
                await cursor.execute(
                    "ALTER TABLE web_auth ADD UNIQUE INDEX uq_web_auth_id_tmp (id)"
                )

        if pk_cols == ["id"]:
            await cursor.execute("ALTER TABLE web_auth DROP PRIMARY KEY")
            await cursor.execute("ALTER TABLE web_auth ADD PRIMARY KEY (discord_id)")
        elif pk_cols == []:
            await cursor.execute("ALTER TABLE web_auth ADD PRIMARY KEY (discord_id)")

        if await self._column_is_auto_increment(cursor, "web_auth", "id"):
            await cursor.execute("ALTER TABLE web_auth MODIFY COLUMN id INT UNSIGNED NOT NULL")

        if await self._index_exists(cursor, "web_auth", "uq_web_auth_id_tmp"):
            await cursor.execute("ALTER TABLE web_auth DROP INDEX uq_web_auth_id_tmp")

        await cursor.execute("ALTER TABLE web_auth DROP COLUMN id")
        self.logger.info("Migrated web_auth PK successfully.")

    async def _migrate_service_principals_hash_only(self, cursor) -> None:
        """
        Guarded migration for service_principals to hash-only token storage.

        Runtime contract:
        - lookup by token_hash only
        - no plaintext token column in active schema
        """
        if not await self._table_exists(cursor, "service_principals"):
            return

        has_legacy_token = await self._column_exists(
            cursor, "service_principals", "token"
        )
        has_token_hash = await self._column_exists(
            cursor, "service_principals", "token_hash"
        )

        if not has_token_hash:
            try:
                await cursor.execute(
                    "ALTER TABLE service_principals ADD COLUMN token_hash VARCHAR(64) NULL"
                )
            except Exception as exc:
                # Race/idempotency-safe behavior:
                # if DB reports duplicate column, verify actual presence and continue.
                err_code = exc.args[0] if getattr(exc, "args", None) else None
                if err_code != 1060 or not await self._column_exists(
                    cursor, "service_principals", "token_hash"
                ):
                    raise RuntimeError(
                        "service_principals migration failed: cannot add token_hash column."
                    ) from exc

            has_token_hash = await self._column_exists(
                cursor, "service_principals", "token_hash"
            )
            has_legacy_token = await self._column_exists(
                cursor, "service_principals", "token"
            )
            if not has_token_hash:
                raise RuntimeError(
                    "service_principals migration failed: token_hash column not present after ALTER."
                )

        if has_legacy_token:
            await cursor.execute(
                """
                UPDATE service_principals
                SET token_hash = SHA2(token, 256)
                WHERE (token_hash IS NULL OR token_hash = '')
                  AND token IS NOT NULL
                  AND token != ''
                """
            )

        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM service_principals
            WHERE is_active = 1
              AND (token_hash IS NULL OR token_hash = '')
            """
        )
        active_missing_row = await cursor.fetchone() or {}
        active_missing = int(active_missing_row.get("cnt", 0))
        if active_missing > 0:
            raise RuntimeError(
                "service_principals migration failed: active principals without token_hash found. "
                "Manual intervention required."
            )

        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM service_principals
            WHERE token_hash IS NULL OR token_hash = ''
            """
        )
        total_missing_row = await cursor.fetchone() or {}
        total_missing = int(total_missing_row.get("cnt", 0))
        if total_missing > 0:
            raise RuntimeError(
                "service_principals migration failed: rows without token_hash remain. "
                "Manual intervention required."
            )

        # Deduplicate legacy token hashes before adding/validating unique constraint.
        configured_names = set(Config.service_token_map.keys())
        await cursor.execute(
            """
            SELECT name, token_hash, is_active
            FROM service_principals
            WHERE token_hash IS NOT NULL
              AND token_hash != ''
            """
        )
        hash_rows = await cursor.fetchall() or []
        dedup_updates, conflict_groups = self._plan_service_principal_token_hash_dedup(
            hash_rows,
            configured_names,
        )
        if dedup_updates:
            for item in dedup_updates:
                await cursor.execute(
                    """
                    UPDATE service_principals
                    SET token_hash = %s, is_active = 0
                    WHERE name = %s
                    """,
                    (item["new_hash"], item["name"]),
                )
            shadowed_names = ", ".join(sorted(item["name"] for item in dedup_updates))
            self.logger.warning(
                "service_principals dedup remediated %s legacy rows across %s conflict groups; "
                "shadowed names: %s",
                len(dedup_updates),
                conflict_groups,
                shadowed_names,
            )
        else:
            self.logger.info(
                "service_principals dedup found no token_hash conflicts (groups=%s).",
                conflict_groups,
            )

        await cursor.execute(
            """
            SELECT token_hash, COUNT(*) AS cnt
            FROM service_principals
            WHERE token_hash IS NOT NULL
              AND token_hash != ''
            GROUP BY token_hash
            HAVING COUNT(*) > 1
            """
        )
        duplicates_after_dedup = await cursor.fetchall() or []
        if duplicates_after_dedup:
            self.logger.error(
                "service_principals dedup conflicts remaining: %s",
                len(duplicates_after_dedup),
            )
            raise RuntimeError(
                "service_principals migration failed: token_hash duplicates remain; "
                "manual intervention required."
            )
        self.logger.info("service_principals dedup conflicts remaining: 0")

        await cursor.execute(
            "ALTER TABLE service_principals MODIFY COLUMN token_hash VARCHAR(64) NOT NULL"
        )

        await cursor.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.statistics
            WHERE table_schema = DATABASE()
              AND table_name = 'service_principals'
              AND column_name = 'token_hash'
              AND non_unique = 0
            """
        )
        uniq_row = await cursor.fetchone() or {}
        if int(uniq_row.get("cnt", 0)) == 0:
            await cursor.execute(
                "ALTER TABLE service_principals ADD UNIQUE INDEX uq_service_token_hash (token_hash)"
            )

        if has_legacy_token:
            await cursor.execute(
                "UPDATE service_principals SET token = NULL WHERE token IS NOT NULL"
            )
            await cursor.execute("ALTER TABLE service_principals DROP COLUMN token")

    async def _init_default_permissions(self, conn):
        """Initialize default role permissions without clobbering custom overrides."""
        async with conn.cursor() as cursor:
            catalog = self._sorted_permission_catalog()
            default_permissions = _default_role_permissions()

            for role, permissions in default_permissions.items():
                await cursor.execute(
                    "SELECT permissions FROM role_permissions WHERE role = %s",
                    (role,),
                )
                row = await cursor.fetchone()

                existing_permissions: dict[str, bool] = {}
                if row and row.get("permissions"):
                    raw = row["permissions"]
                    if isinstance(raw, str):
                        try:
                            existing_permissions = json.loads(raw)
                        except json.JSONDecodeError:
                            existing_permissions = {}
                    elif isinstance(raw, dict):
                        existing_permissions = raw

                translated_existing = normalize_permission_flags(existing_permissions)
                base_permissions = {
                    key: bool(permissions.get(key, False))
                    for key in catalog
                }
                for key, value in translated_existing.items():
                    if key in base_permissions:
                        base_permissions[key] = bool(value)
                reconciled = build_dense_permission_map(base_permissions)

                await cursor.execute(
                    """
                    INSERT INTO role_permissions (role, permissions)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE permissions = %s
                    """,
                    (
                        role,
                        json.dumps(reconciled),
                        json.dumps(reconciled),
                    ),
                )
            await conn.commit()
            self.logger.debug("  ✓ Default permissions reconciled")

    async def _init_weekly_payout_config(self, conn):
        """Seed config-driven payout metadata for weekly assistant reviews."""
        type_rules = {
            "EXP": "giveexp",
            "Premium": "setvip",
            "MC": "givedonate",
            "MONEY": "givemoney",
        }
        amount_rules = {
            ("junior", "EXP", "Актив"): "20000",
            ("junior", "EXP", "Ультра-Актив"): "35000",
            ("junior", "Premium", "Актив"): "4",
            ("junior", "Premium", "Ультра-Актив"): "7",
            ("junior", "MC", "Актив"): "1000",
            ("junior", "MC", "Ультра-Актив"): "1200",
            ("junior", "MONEY", "Актив"): "150000",
            ("junior", "MONEY", "Ультра-Актив"): "200000",
            ("default", "EXP", "Актив"): "35000",
            ("default", "EXP", "Ультра-Актив"): "50000",
            ("default", "Premium", "Актив"): "7",
            ("default", "Premium", "Ультра-Актив"): "14",
            ("default", "MC", "Актив"): "1200",
            ("default", "MC", "Ультра-Актив"): "2000",
            ("default", "MONEY", "Актив"): "200000",
            ("default", "MONEY", "Ультра-Актив"): "250000",
            ("Senior", "EXP", "Актив"): "35000",
            ("Senior", "EXP", "Ультра-Актив"): "50000",
            ("Senior", "Premium", "Актив"): "7",
            ("Senior", "Premium", "Ультра-Актив"): "14",
            ("Senior", "MC", "Актив"): "1200",
            ("Senior", "MC", "Ультра-Актив"): "2000",
            ("Senior", "MONEY", "Актив"): "200000",
            ("Senior", "MONEY", "Ультра-Актив"): "250000",
        }
        async with conn.cursor() as cursor:
            for payout_type, command_name in type_rules.items():
                await cursor.execute(
                    """
                    INSERT INTO assistant_weekly_payout_type_rules (payout_type, command_name)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE command_name = command_name
                    """,
                    (payout_type, command_name),
                )
            for (role_group, payout_type, result_code), amount in amount_rules.items():
                await cursor.execute(
                    """
                    INSERT INTO assistant_weekly_payout_amount_rules (
                        role_group, payout_type, result_code, amount
                    )
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE amount = amount
                    """,
                    (role_group, payout_type, result_code, amount),
                )
        await conn.commit()
        self.logger.debug("  ✓ Weekly payout config seeded")

    async def _init_default_service_principals(self, conn):
        """Initialize or reconcile service principal scopes for configured tokens."""
        configured = self._configured_service_tokens()
        if not configured:
            return

        async with conn.cursor() as cursor:
            has_token_hash = await self._column_exists(
                cursor, "service_principals", "token_hash"
            )
            if not has_token_hash:
                # Guard against metadata/introspection false-negatives:
                # run migration path once more, then re-check deterministically.
                await self._migrate_service_principals_hash_only(cursor)
                has_token_hash = await self._column_exists(
                    cursor, "service_principals", "token_hash"
                )
            if not has_token_hash:
                raise RuntimeError(
                    "service_principals.token_hash is missing after migrations; "
                    "startup aborted to prevent broken service auth."
                )

            for service_name, token in configured:
                defaults = self._get_default_service_permissions(service_name)
                normalized_token = (token or "").strip()
                if not normalized_token:
                    continue
                token_hash = self._hash_service_token(normalized_token)
                # Configured service tokens are authoritative and must stay active.
                # Scopes are also authoritative: built-in service principals are
                # reconciled back to code-defined least-privilege permissions on startup.
                is_active = True
                base_permissions = build_dense_service_permission_map(defaults)
                reconciled = build_dense_service_permission_map(base_permissions)

                await cursor.execute(
                    """
                    INSERT INTO service_principals (name, token_hash, permissions, is_active)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name = %s,
                        token_hash = %s,
                        permissions = %s,
                        is_active = %s
                    """,
                    (
                        service_name,
                        token_hash,
                        json.dumps(reconciled),
                        is_active,
                        service_name,
                        token_hash,
                        json.dumps(reconciled),
                        is_active,
                    ),
                )

            await conn.commit()
            self.logger.debug("  ✓ Service principals reconciled")

    async def _ensure_singleton_settings(self, conn):
        """Ensure settings table has exactly one row."""
        async with conn.cursor() as cursor:

            await cursor.execute("SELECT COUNT(*) as count FROM settings")

            result = await cursor.fetchone()
            row_count = int(result["count"])

            if row_count == 0:
                self.logger.debug(
                    "  ℹ No settings row found, will be created on first update"
                )
            elif row_count > 1 :
                self.logger.warning(
                    f"  ⚠ Settings table has {row_count} rows, cleaning up to keep only 1..."
                )
                await cursor.execute("SELECT * FROM settings LIMIT 1")

                survivor = await cursor.fetchone()

                await cursor.execute("DELETE FROM settings")
                if survivor:

                    columns = list(survivor.keys())
                    values = [survivor[col] for col in columns]
                    placeholders = ", ".join(["%s"] * len(columns))
                    column_names = ", ".join(columns)

                    await cursor.execute(
                        f"INSERT INTO settings ({column_names}) VALUES ({placeholders})",
                        tuple(values),
                    )
                    self.logger.info("  ✓ Settings table cleaned up to 1 row")

                await conn.commit()
