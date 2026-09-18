"""
Database layer for the rolling window system.
Manages SQLite connections and schema initialization.
Replaces the old ProfileStorage as the single source of truth.
"""

import sqlite3
from pathlib import Path
from typing import Optional

from src.utils import get_logger, get_data_dir

logger = get_logger(__name__)


class Database:
    """SQLite database manager with WAL mode for concurrent webhook access."""

    def __init__(self, db_path: Optional[str] = None):
        data_dir = get_data_dir()
        self.db_path = Path(db_path) if db_path else data_dir / "cache" / "reviewermatch.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info(f"Database initialized: {self.db_path}")

    def connect(self) -> sqlite3.Connection:
        """Open a connection with concurrency-safe settings."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        conn = self.connect()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pr_window (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_name       TEXT NOT NULL,
                pr_number       INTEGER NOT NULL,
                title           TEXT,
                description     TEXT,
                author_username TEXT NOT NULL,
                author_id       INTEGER,
                created_at      TEXT,
                merged_at       TEXT,
                additions       INTEGER DEFAULT 0,
                deletions       INTEGER DEFAULT 0,
                changed_files   TEXT,
                changed_files_count INTEGER DEFAULT 0,
                labels          TEXT,
                window_position INTEGER,
                added_to_window TEXT DEFAULT (datetime('now')),
                UNIQUE(repo_name, pr_number)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pr_reviews (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_window_id        INTEGER NOT NULL,
                repo_name           TEXT NOT NULL,
                pr_number           INTEGER NOT NULL,
                reviewer_username   TEXT NOT NULL,
                reviewer_id         INTEGER,
                review_state        TEXT,
                review_body         TEXT,
                submitted_at        TEXT,
                author_association  TEXT,
                FOREIGN KEY (pr_window_id) REFERENCES pr_window(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pr_review_comments (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_window_id        INTEGER NOT NULL,
                repo_name           TEXT NOT NULL,
                pr_number           INTEGER NOT NULL,
                reviewer_username   TEXT NOT NULL,
                reviewer_id         INTEGER,
                body                TEXT,
                file_path           TEXT,
                line_number         INTEGER,
                submitted_at        TEXT,
                author_association  TEXT,
                FOREIGN KEY (pr_window_id) REFERENCES pr_window(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                username                    TEXT NOT NULL,
                repo_name                   TEXT NOT NULL,
                is_reviewer                 INTEGER DEFAULT 0,
                is_developer                INTEGER DEFAULT 0,
                total_reviews               INTEGER DEFAULT 0,
                total_review_comments       INTEGER DEFAULT 0,
                reviews_approved            INTEGER DEFAULT 0,
                reviews_changes_requested   INTEGER DEFAULT 0,
                reviews_commented           INTEGER DEFAULT 0,
                total_prs_authored          INTEGER DEFAULT 0,
                total_additions             INTEGER DEFAULT 0,
                total_deletions             INTEGER DEFAULT 0,
                experience_level            TEXT,
                primary_skills              TEXT,
                programming_languages       TEXT,
                summary                     TEXT,
                javascript_skill_matrix     TEXT,
                profile_json                TEXT,
                created_at                  TEXT DEFAULT (datetime('now')),
                updated_at                  TEXT DEFAULT (datetime('now')),
                UNIQUE(username, repo_name)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_skills (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT NOT NULL,
                repo_name       TEXT NOT NULL,
                skill_name      TEXT NOT NULL,
                skill_category  TEXT,
                frequency       INTEGER DEFAULT 0,
                FOREIGN KEY (username, repo_name)
                    REFERENCES user_profiles(username, repo_name) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pr_user_contributions (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_window_id                INTEGER NOT NULL,
                repo_name                   TEXT NOT NULL,
                pr_number                   INTEGER NOT NULL,
                username                    TEXT NOT NULL,
                contribution_type           TEXT NOT NULL,
                skill_deltas                TEXT,
                review_count_delta          INTEGER DEFAULT 0,
                review_comment_delta        INTEGER DEFAULT 0,
                pr_authored_delta           INTEGER DEFAULT 0,
                additions_delta             INTEGER DEFAULT 0,
                deletions_delta             INTEGER DEFAULT 0,
                approved_delta              INTEGER DEFAULT 0,
                changes_requested_delta     INTEGER DEFAULT 0,
                commented_delta             INTEGER DEFAULT 0,
                FOREIGN KEY (pr_window_id) REFERENCES pr_window(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assignment_history (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_number           INTEGER,
                repo_name           TEXT,
                pr_author           TEXT,
                suggested_reviewers TEXT,
                assigned_at         TEXT DEFAULT (datetime('now')),
                confidence_score    REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS repo_metadata (
                repo_name           TEXT PRIMARY KEY,
                is_fork             INTEGER DEFAULT 0,
                parent_repo         TEXT,
                window_size         INTEGER DEFAULT 0,
                max_window_size     INTEGER DEFAULT 500,
                last_setup_at       TEXT,
                last_pr_merged_at   TEXT,
                faiss_index_built   INTEGER DEFAULT 0,
                created_at          TEXT DEFAULT (datetime('now')),
                updated_at          TEXT DEFAULT (datetime('now'))
            )
        """)

        # Indexes
        for stmt in [
            "CREATE INDEX IF NOT EXISTS idx_pr_window_repo ON pr_window(repo_name)",
            "CREATE INDEX IF NOT EXISTS idx_pr_window_repo_pos ON pr_window(repo_name, window_position)",
            "CREATE INDEX IF NOT EXISTS idx_pr_window_author ON pr_window(author_username)",
            "CREATE INDEX IF NOT EXISTS idx_pr_window_merged ON pr_window(repo_name, merged_at)",
            "CREATE INDEX IF NOT EXISTS idx_pr_reviews_reviewer ON pr_reviews(reviewer_username)",
            "CREATE INDEX IF NOT EXISTS idx_pr_reviews_repo ON pr_reviews(repo_name)",
            "CREATE INDEX IF NOT EXISTS idx_pr_reviews_pr ON pr_reviews(pr_window_id)",
            "CREATE INDEX IF NOT EXISTS idx_pr_review_comments_reviewer ON pr_review_comments(reviewer_username)",
            "CREATE INDEX IF NOT EXISTS idx_pr_review_comments_file ON pr_review_comments(file_path)",
            "CREATE INDEX IF NOT EXISTS idx_user_profiles_repo ON user_profiles(repo_name)",
            "CREATE INDEX IF NOT EXISTS idx_user_profiles_user ON user_profiles(username)",
            "CREATE INDEX IF NOT EXISTS idx_user_profiles_reviewer ON user_profiles(repo_name, is_reviewer)",
            "CREATE INDEX IF NOT EXISTS idx_user_profiles_developer ON user_profiles(repo_name, is_developer)",
            "CREATE INDEX IF NOT EXISTS idx_user_skills_skill ON user_skills(skill_name)",
            "CREATE INDEX IF NOT EXISTS idx_user_skills_user ON user_skills(username, repo_name)",
            "CREATE INDEX IF NOT EXISTS idx_contributions_pr ON pr_user_contributions(pr_window_id)",
            "CREATE INDEX IF NOT EXISTS idx_contributions_user ON pr_user_contributions(username, repo_name)",
        ]:
            cursor.execute(stmt)

        conn.commit()
        conn.close()
