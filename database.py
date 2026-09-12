"""
SQLite database manager for tracking applied jobs, deduplication, and daily quotas.
"""

from datetime import datetime, date
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional


class JobDatabase:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = Path(__file__).parent.resolve()
            data_dir = base_dir / "data"
            data_dir.mkdir(exist_ok=True, parents=True)
            self.db_path = data_dir / "jobs.db"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(exist_ok=True, parents=True)

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes database tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    title TEXT,
                    company TEXT,
                    location TEXT,
                    job_url TEXT,
                    status TEXT NOT NULL,
                    reason TEXT,
                    applied_date TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    UNIQUE(job_id, platform)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    applied_count INTEGER DEFAULT 0,
                    limit_reached INTEGER DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(date, platform)
                )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_apps_date_platform ON applications(applied_date, platform)")
            conn.commit()

    def is_job_applied(self, job_id: str, platform: str) -> bool:
        """Checks if a job has already been applied to or recorded (including user skipped)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM applications WHERE job_id = ? AND platform = ? AND status in ('applied', 'skipped')",
                (str(job_id), platform),
            )
            return cursor.fetchone() is not None

    def is_url_or_company_applied(
        self,
        job_url: str = "",
        company: str = "",
        title: str = "",
    ) -> bool:
        """
        Checks across all records if an application for this specific external URL
        or company + title combination has already been applied or skipped.
        Prevents visiting external company career sites multiple times.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Match by external URL if available
            if job_url and len(job_url) > 12 and not job_url.startswith("about:"):
                clean_url = job_url.split("?")[0].rstrip("/")
                cursor.execute(
                    "SELECT 1 FROM applications WHERE (job_url = ? OR job_url LIKE ?) AND status in ('applied', 'skipped')",
                    (job_url, f"{clean_url}%"),
                )
                if cursor.fetchone() is not None:
                    return True

            # 2. Match by normalized Company + Title
            if company and title and company.lower() not in ("unknown company", "company", ""):
                cursor.execute(
                    "SELECT 1 FROM applications WHERE LOWER(TRIM(company)) = LOWER(TRIM(?)) "
                    "AND LOWER(TRIM(title)) = LOWER(TRIM(?)) AND status in ('applied', 'skipped')",
                    (company, title),
                )
                if cursor.fetchone() is not None:
                    return True

        return False

    def record_application(
        self,
        job_id: str,
        platform: str,
        title: str,
        company: str,
        location: str = "",
        job_url: str = "",
        status: str = "applied",
        reason: str = "",
    ):
        """Records an application attempt and updates daily counters."""
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        timestamp_str = now.isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO applications (job_id, platform, title, company, location, job_url, status, reason, applied_date, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, platform) DO UPDATE SET
                    status = excluded.status,
                    reason = excluded.reason,
                    timestamp = excluded.timestamp
                """,
                (str(job_id), platform, title, company, location, job_url, status, reason, today_str, timestamp_str),
            )

            if status == "applied":
                cursor.execute(
                    """
                    INSERT INTO daily_stats (date, platform, applied_count, limit_reached, updated_at)
                    VALUES (?, ?, 1, 0, ?)
                    ON CONFLICT(date, platform) DO UPDATE SET
                        applied_count = applied_count + 1,
                        updated_at = excluded.updated_at
                    """,
                    (today_str, platform, timestamp_str),
                )
            conn.commit()

    def get_daily_applied_count(self, platform: str, target_date: Optional[str] = None) -> int:
        """Returns the number of successful applications made today for a platform."""
        today_str = target_date or date.today().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT applied_count FROM daily_stats WHERE date = ? AND platform = ?",
                (today_str, platform),
            )
            row = cursor.fetchone()
            return row["applied_count"] if row else 0

    def is_daily_limit_reached(self, platform: str, target_date: Optional[str] = None) -> bool:
        """Checks whether the platform hit its hard daily limit today."""
        today_str = target_date or date.today().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT limit_reached FROM daily_stats WHERE date = ? AND platform = ?",
                (today_str, platform),
            )
            row = cursor.fetchone()
            return bool(row["limit_reached"]) if row else False

    def mark_daily_limit_reached(self, platform: str, target_date: Optional[str] = None):
        """Marks the platform as having reached its daily quota limit for today."""
        now = datetime.now()
        today_str = target_date or now.strftime("%Y-%m-%d")
        timestamp_str = now.isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO daily_stats (date, platform, applied_count, limit_reached, updated_at)
                VALUES (?, ?, 0, 1, ?)
                ON CONFLICT(date, platform) DO UPDATE SET
                    limit_reached = 1,
                    updated_at = excluded.updated_at
                """,
                (today_str, platform, timestamp_str),
            )
            conn.commit()

    def get_recent_applications(
        self,
        limit: Optional[int] = 20,
        platform: Optional[str] = None,
        status: Optional[str] = "applied",
    ) -> List[Dict[str, Any]]:
        """Returns the application records, with optional limit, platform and status filtering."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT job_id, platform, title, company, location, status, reason, timestamp, job_url FROM applications"
            conditions = []
            params = []
            if status:
                conditions.append("status = ?")
                params.append(status)
            if platform and platform.lower() != "all":
                conditions.append("platform = ?")
                params.append(platform.lower())

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY timestamp DESC"
            if limit is not None and limit > 0:
                query += " LIMIT ?"
                params.append(limit)

            cursor.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]

    def get_summary_stats(self) -> Dict[str, Any]:
        """Returns high-level statistics for reporting."""
        today_str = date.today().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Total applied
            cursor.execute("SELECT COUNT(*) as total FROM applications WHERE status = 'applied'")
            total_applied = cursor.fetchone()["total"]

            # Today applied per platform
            today_stats = {}
            cursor.execute("SELECT platform, applied_count, limit_reached FROM daily_stats WHERE date = ?", (today_str,))
            for row in cursor.fetchall():
                today_stats[row["platform"]] = {
                    "count": row["applied_count"],
                    "limit_reached": bool(row["limit_reached"]),
                }

            return {
                "date": today_str,
                "total_all_time": total_applied,
                "today": today_stats,
            }
