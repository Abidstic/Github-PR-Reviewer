"""
Window Manager — the core of the rolling window system.

Manages a per-repo window of the latest 500 merged PRs.
Handles adding new PRs, evicting old ones, and tracking
what each PR contributed to user profiles (for subtraction).
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.storage.database import Database
from src.utils import get_logger, get_config

logger = get_logger(__name__)


class WindowManager:
    """Manages the rolling window of PRs and user profile stats."""

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self.config = get_config()
        self.max_window_size = 500

    # ------------------------------------------------------------------
    # Repo metadata
    # ------------------------------------------------------------------

    def init_repo(self, repo_name: str, is_fork: bool = False,
                  parent_repo: Optional[str] = None) -> None:
        """Register a repo. Safe to call multiple times (upsert)."""
        conn = self.db.connect()
        conn.execute("""
            INSERT INTO repo_metadata (repo_name, is_fork, parent_repo, last_setup_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(repo_name) DO UPDATE SET
                is_fork = excluded.is_fork,
                parent_repo = excluded.parent_repo,
                last_setup_at = excluded.last_setup_at,
                updated_at = datetime('now')
        """, (repo_name, int(is_fork), parent_repo, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

    def get_repo_metadata(self, repo_name: str) -> Optional[Dict]:
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM repo_metadata WHERE repo_name = ?", (repo_name,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Window queries
    # ------------------------------------------------------------------

    def get_window_size(self, repo_name: str) -> int:
        conn = self.db.connect()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM pr_window WHERE repo_name = ?",
            (repo_name,)
        ).fetchone()
        conn.close()
        return row['cnt']

    def get_window_prs(self, repo_name: str) -> List[Dict]:
        """Return all PRs in the window, oldest first."""
        conn = self.db.connect()
        rows = conn.execute(
            "SELECT * FROM pr_window WHERE repo_name = ? ORDER BY window_position ASC",
            (repo_name,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def is_pr_in_window(self, repo_name: str, pr_number: int) -> bool:
        conn = self.db.connect()
        row = conn.execute(
            "SELECT 1 FROM pr_window WHERE repo_name = ? AND pr_number = ?",
            (repo_name, pr_number)
        ).fetchone()
        conn.close()
        return row is not None

    def get_oldest_pr(self, repo_name: str) -> Optional[Dict]:
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM pr_window WHERE repo_name = ? ORDER BY window_position ASC LIMIT 1",
            (repo_name,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Add a merged PR to the window
    # ------------------------------------------------------------------

    def add_pr(self, pr_data: Dict, reviews: List[Dict],
               review_comments: List[Dict]) -> Optional[int]:
        """
        Add a merged PR to the rolling window.

        Args:
            pr_data: PR metadata dict with keys: repo_name, pr_number, title,
                     description, author_username, author_id, created_at,
                     merged_at, additions, deletions, changed_files (list),
                     changed_files_count, labels (list)
            reviews: list of review dicts with keys: reviewer_username,
                     reviewer_id, review_state, review_body, submitted_at,
                     author_association
            review_comments: list of line-level comment dicts with keys:
                     reviewer_username, reviewer_id, body, file_path,
                     line_number, submitted_at, author_association

        Returns:
            The pr_window.id of the inserted row, or None if already present.
        """
        repo_name = pr_data['repo_name']
        pr_number = pr_data['pr_number']

        if self.is_pr_in_window(repo_name, pr_number):
            logger.info(f"PR #{pr_number} already in window for {repo_name}")
            return None

        conn = self.db.connect()
        try:
            # Determine the next window position
            row = conn.execute(
                "SELECT COALESCE(MAX(window_position), 0) as max_pos "
                "FROM pr_window WHERE repo_name = ?",
                (repo_name,)
            ).fetchone()
            next_pos = row['max_pos'] + 1

            # Insert PR into window
            cursor = conn.execute("""
                INSERT INTO pr_window (
                    repo_name, pr_number, title, description,
                    author_username, author_id, created_at, merged_at,
                    additions, deletions, changed_files, changed_files_count,
                    labels, window_position
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                repo_name, pr_number,
                pr_data.get('title', ''),
                pr_data.get('description', ''),
                pr_data['author_username'],
                pr_data.get('author_id'),
                pr_data.get('created_at'),
                pr_data.get('merged_at'),
                pr_data.get('additions', 0),
                pr_data.get('deletions', 0),
                json.dumps(pr_data.get('changed_files', [])),
                pr_data.get('changed_files_count', 0),
                json.dumps(pr_data.get('labels', [])),
                next_pos,
            ))
            pr_window_id = cursor.lastrowid

            # Insert reviews
            for review in reviews:
                conn.execute("""
                    INSERT INTO pr_reviews (
                        pr_window_id, repo_name, pr_number,
                        reviewer_username, reviewer_id, review_state,
                        review_body, submitted_at, author_association
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pr_window_id, repo_name, pr_number,
                    review['reviewer_username'],
                    review.get('reviewer_id'),
                    review.get('review_state', review.get('state')),
                    review.get('review_body', review.get('body', '')),
                    review.get('submitted_at'),
                    review.get('author_association'),
                ))

            # Insert review comments
            for comment in review_comments:
                conn.execute("""
                    INSERT INTO pr_review_comments (
                        pr_window_id, repo_name, pr_number,
                        reviewer_username, reviewer_id, body,
                        file_path, line_number, submitted_at,
                        author_association
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pr_window_id, repo_name, pr_number,
                    comment['reviewer_username'],
                    comment.get('reviewer_id'),
                    comment.get('body', ''),
                    comment.get('file_path', comment.get('path', '')),
                    comment.get('line_number', comment.get('line')),
                    comment.get('submitted_at', comment.get('created_at')),
                    comment.get('author_association'),
                ))

            # Record contributions for the PR author
            self._record_author_contribution(
                conn, pr_window_id, repo_name, pr_number, pr_data
            )

            # Record contributions for each reviewer
            self._record_reviewer_contributions(
                conn, pr_window_id, repo_name, pr_number, reviews, review_comments
            )

            # Update repo metadata
            conn.execute("""
                UPDATE repo_metadata
                SET window_size = (SELECT COUNT(*) FROM pr_window WHERE repo_name = ?),
                    last_pr_merged_at = ?,
                    updated_at = datetime('now')
                WHERE repo_name = ?
            """, (repo_name, pr_data.get('merged_at'), repo_name))

            conn.commit()
            logger.info(
                f"Added PR #{pr_number} to window for {repo_name} "
                f"(position {next_pos})"
            )
            return pr_window_id

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to add PR #{pr_number}: {e}")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Evict the oldest PR
    # ------------------------------------------------------------------

    def evict_oldest(self, repo_name: str) -> Optional[Dict]:
        """
        Remove the oldest PR from the window and subtract its
        contributions from affected user profiles.

        Returns:
            The evicted PR data dict, or None if window was empty.
        """
        oldest = self.get_oldest_pr(repo_name)
        if not oldest:
            return None

        pr_window_id = oldest['id']
        conn = self.db.connect()
        try:
            # Load contributions for this PR
            contributions = conn.execute(
                "SELECT * FROM pr_user_contributions WHERE pr_window_id = ?",
                (pr_window_id,)
            ).fetchall()

            # Subtract each contribution from the user's profile
            for contrib in contributions:
                self._subtract_contribution(conn, dict(contrib))

            # Delete the PR row — CASCADE handles reviews, comments, contributions
            conn.execute("DELETE FROM pr_window WHERE id = ?", (pr_window_id,))

            # Update repo metadata
            conn.execute("""
                UPDATE repo_metadata
                SET window_size = (SELECT COUNT(*) FROM pr_window WHERE repo_name = ?),
                    updated_at = datetime('now')
                WHERE repo_name = ?
            """, (repo_name, repo_name))

            conn.commit()
            logger.info(
                f"Evicted PR #{oldest['pr_number']} from {repo_name} window "
                f"(was position {oldest['window_position']})"
            )
            return dict(oldest)

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to evict oldest PR: {e}")
            raise
        finally:
            conn.close()

    def evict_if_full(self, repo_name: str) -> Optional[Dict]:
        """Evict the oldest PR only if the window exceeds max size."""
        size = self.get_window_size(repo_name)
        if size > self.max_window_size:
            return self.evict_oldest(repo_name)
        return None

    # ------------------------------------------------------------------
    # Contribution recording
    # ------------------------------------------------------------------

    def _record_author_contribution(self, conn, pr_window_id: int,
                                     repo_name: str, pr_number: int,
                                     pr_data: Dict) -> None:
        """Record what this PR contributes to the author's profile."""
        username = pr_data['author_username']

        # Ensure user_profiles row exists
        self._ensure_user_profile(conn, username, repo_name)

        # Update the profile stats
        conn.execute("""
            UPDATE user_profiles SET
                is_developer = 1,
                total_prs_authored = total_prs_authored + 1,
                total_additions = total_additions + ?,
                total_deletions = total_deletions + ?,
                updated_at = datetime('now')
            WHERE username = ? AND repo_name = ?
        """, (
            pr_data.get('additions', 0),
            pr_data.get('deletions', 0),
            username, repo_name
        ))

        # Record the contribution so we can subtract later
        conn.execute("""
            INSERT INTO pr_user_contributions (
                pr_window_id, repo_name, pr_number, username,
                contribution_type, pr_authored_delta,
                additions_delta, deletions_delta
            ) VALUES (?, ?, ?, ?, 'author', 1, ?, ?)
        """, (
            pr_window_id, repo_name, pr_number, username,
            pr_data.get('additions', 0),
            pr_data.get('deletions', 0),
        ))

    def _record_reviewer_contributions(self, conn, pr_window_id: int,
                                        repo_name: str, pr_number: int,
                                        reviews: List[Dict],
                                        review_comments: List[Dict]) -> None:
        """Record what this PR contributes to each reviewer's profile."""
        # Aggregate per reviewer: one contribution row per reviewer per PR
        reviewer_data: Dict[str, Dict] = {}

        for review in reviews:
            username = review['reviewer_username']
            if username not in reviewer_data:
                reviewer_data[username] = {
                    'review_count': 0,
                    'review_comment_count': 0,
                    'approved': 0,
                    'changes_requested': 0,
                    'commented': 0,
                }
            rd = reviewer_data[username]
            rd['review_count'] += 1
            state = review.get('review_state', review.get('state', ''))
            if state == 'APPROVED':
                rd['approved'] += 1
            elif state == 'CHANGES_REQUESTED':
                rd['changes_requested'] += 1
            elif state == 'COMMENTED':
                rd['commented'] += 1

        for comment in review_comments:
            username = comment['reviewer_username']
            if username not in reviewer_data:
                reviewer_data[username] = {
                    'review_count': 0,
                    'review_comment_count': 0,
                    'approved': 0,
                    'changes_requested': 0,
                    'commented': 0,
                }
            reviewer_data[username]['review_comment_count'] += 1

        # Write to profile + contribution table for each reviewer
        for username, data in reviewer_data.items():
            self._ensure_user_profile(conn, username, repo_name)

            conn.execute("""
                UPDATE user_profiles SET
                    is_reviewer = 1,
                    total_reviews = total_reviews + ?,
                    total_review_comments = total_review_comments + ?,
                    reviews_approved = reviews_approved + ?,
                    reviews_changes_requested = reviews_changes_requested + ?,
                    reviews_commented = reviews_commented + ?,
                    updated_at = datetime('now')
                WHERE username = ? AND repo_name = ?
            """, (
                data['review_count'],
                data['review_comment_count'],
                data['approved'],
                data['changes_requested'],
                data['commented'],
                username, repo_name
            ))

            conn.execute("""
                INSERT INTO pr_user_contributions (
                    pr_window_id, repo_name, pr_number, username,
                    contribution_type, review_count_delta,
                    review_comment_delta, approved_delta,
                    changes_requested_delta, commented_delta
                ) VALUES (?, ?, ?, ?, 'review', ?, ?, ?, ?, ?)
            """, (
                pr_window_id, repo_name, pr_number, username,
                data['review_count'],
                data['review_comment_count'],
                data['approved'],
                data['changes_requested'],
                data['commented'],
            ))

    # ------------------------------------------------------------------
    # Contribution subtraction (on eviction)
    # ------------------------------------------------------------------

    def _subtract_contribution(self, conn, contrib: Dict) -> None:
        """Subtract one PR's contribution from the user's profile."""
        username = contrib['username']
        repo_name = contrib['repo_name']
        ctype = contrib['contribution_type']

        if ctype == 'author':
            conn.execute("""
                UPDATE user_profiles SET
                    total_prs_authored = MAX(total_prs_authored - ?, 0),
                    total_additions = MAX(total_additions - ?, 0),
                    total_deletions = MAX(total_deletions - ?, 0),
                    updated_at = datetime('now')
                WHERE username = ? AND repo_name = ?
            """, (
                contrib['pr_authored_delta'],
                contrib['additions_delta'],
                contrib['deletions_delta'],
                username, repo_name
            ))

            # If user has no more authored PRs, clear developer flag
            row = conn.execute(
                "SELECT total_prs_authored FROM user_profiles "
                "WHERE username = ? AND repo_name = ?",
                (username, repo_name)
            ).fetchone()
            if row and row['total_prs_authored'] <= 0:
                conn.execute(
                    "UPDATE user_profiles SET is_developer = 0 "
                    "WHERE username = ? AND repo_name = ?",
                    (username, repo_name)
                )

        elif ctype == 'review':
            conn.execute("""
                UPDATE user_profiles SET
                    total_reviews = MAX(total_reviews - ?, 0),
                    total_review_comments = MAX(total_review_comments - ?, 0),
                    reviews_approved = MAX(reviews_approved - ?, 0),
                    reviews_changes_requested = MAX(reviews_changes_requested - ?, 0),
                    reviews_commented = MAX(reviews_commented - ?, 0),
                    updated_at = datetime('now')
                WHERE username = ? AND repo_name = ?
            """, (
                contrib['review_count_delta'],
                contrib['review_comment_delta'],
                contrib['approved_delta'],
                contrib['changes_requested_delta'],
                contrib['commented_delta'],
                username, repo_name
            ))

            # If user has no more reviews, clear reviewer flag
            row = conn.execute(
                "SELECT total_reviews, total_review_comments FROM user_profiles "
                "WHERE username = ? AND repo_name = ?",
                (username, repo_name)
            ).fetchone()
            if row and row['total_reviews'] <= 0 and row['total_review_comments'] <= 0:
                conn.execute(
                    "UPDATE user_profiles SET is_reviewer = 0 "
                    "WHERE username = ? AND repo_name = ?",
                    (username, repo_name)
                )

        # Subtract skill deltas if present
        skill_deltas_raw = contrib.get('skill_deltas')
        if skill_deltas_raw:
            skill_deltas = json.loads(skill_deltas_raw) if isinstance(skill_deltas_raw, str) else skill_deltas_raw
            for skill_name, delta in skill_deltas.items():
                conn.execute("""
                    UPDATE user_skills
                    SET frequency = MAX(frequency - ?, 0)
                    WHERE username = ? AND repo_name = ? AND skill_name = ?
                """, (delta, username, repo_name, skill_name))

            # Clean up zero-frequency skills
            conn.execute("""
                DELETE FROM user_skills
                WHERE username = ? AND repo_name = ? AND frequency <= 0
            """, (username, repo_name))

        # Clean up empty profiles (no reviews, no authored PRs, no skills)
        row = conn.execute(
            "SELECT total_reviews, total_review_comments, total_prs_authored "
            "FROM user_profiles WHERE username = ? AND repo_name = ?",
            (username, repo_name)
        ).fetchone()
        if row and row['total_reviews'] <= 0 and row['total_review_comments'] <= 0 and row['total_prs_authored'] <= 0:
            conn.execute(
                "DELETE FROM user_profiles WHERE username = ? AND repo_name = ?",
                (username, repo_name)
            )
            logger.debug(f"Removed empty profile for {username} in {repo_name}")

    # ------------------------------------------------------------------
    # User profile helpers
    # ------------------------------------------------------------------

    def _ensure_user_profile(self, conn, username: str, repo_name: str) -> None:
        """Create a user_profiles row if one doesn't exist."""
        conn.execute("""
            INSERT OR IGNORE INTO user_profiles (username, repo_name)
            VALUES (?, ?)
        """, (username, repo_name))

    def get_user_profile(self, username: str, repo_name: str) -> Optional[Dict]:
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM user_profiles WHERE username = ? AND repo_name = ?",
            (username, repo_name)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_users(self, repo_name: str,
                      include_developers: bool = True) -> List[Dict]:
        """Get all user profiles for a repo (for reviewer matching)."""
        conn = self.db.connect()
        if include_developers:
            rows = conn.execute(
                "SELECT * FROM user_profiles WHERE repo_name = ? "
                "AND (is_reviewer = 1 OR is_developer = 1)",
                (repo_name,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM user_profiles WHERE repo_name = ? AND is_reviewer = 1",
                (repo_name,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_user_skills(self, username: str, repo_name: str) -> List[Dict]:
        conn = self.db.connect()
        rows = conn.execute(
            "SELECT * FROM user_skills WHERE username = ? AND repo_name = ?",
            (username, repo_name)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Data gathering (for profile builder)
    # ------------------------------------------------------------------

    def get_user_authored_prs(self, username: str, repo_name: str) -> List[Dict]:
        """Get all PRs in the window authored by this user."""
        conn = self.db.connect()
        rows = conn.execute(
            "SELECT * FROM pr_window WHERE author_username = ? AND repo_name = ? "
            "ORDER BY window_position ASC",
            (username, repo_name)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_user_reviews(self, username: str, repo_name: str) -> List[Dict]:
        """Get all reviews in the window by this user, with PR context."""
        conn = self.db.connect()
        rows = conn.execute("""
            SELECT r.*, p.title as pr_title, p.description as pr_description,
                   p.changed_files, p.labels
            FROM pr_reviews r
            JOIN pr_window p ON r.pr_window_id = p.id
            WHERE r.reviewer_username = ? AND r.repo_name = ?
            ORDER BY r.submitted_at ASC
        """, (username, repo_name)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_user_review_comments(self, username: str, repo_name: str) -> List[Dict]:
        """Get all review comments in the window by this user."""
        conn = self.db.connect()
        rows = conn.execute(
            "SELECT * FROM pr_review_comments "
            "WHERE reviewer_username = ? AND repo_name = ? "
            "ORDER BY submitted_at ASC",
            (username, repo_name)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_pr_by_id(self, pr_window_id: int) -> Optional[Dict]:
        """Get a single PR from the window by its ID."""
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM pr_window WHERE id = ?", (pr_window_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_pr_reviews(self, pr_window_id: int) -> List[Dict]:
        """Get all reviews for a specific PR in the window."""
        conn = self.db.connect()
        rows = conn.execute(
            "SELECT * FROM pr_reviews WHERE pr_window_id = ?",
            (pr_window_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_pr_review_comments(self, pr_window_id: int) -> List[Dict]:
        """Get all review comments for a specific PR in the window."""
        conn = self.db.connect()
        rows = conn.execute(
            "SELECT * FROM pr_review_comments WHERE pr_window_id = ?",
            (pr_window_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_involved_users(self, pr_window_id: int) -> List[str]:
        """Get all usernames involved in a PR (author + reviewers)."""
        conn = self.db.connect()
        pr = conn.execute(
            "SELECT author_username FROM pr_window WHERE id = ?",
            (pr_window_id,)
        ).fetchone()

        usernames = set()
        if pr:
            usernames.add(pr['author_username'])

        reviewers = conn.execute(
            "SELECT DISTINCT reviewer_username FROM pr_reviews "
            "WHERE pr_window_id = ?",
            (pr_window_id,)
        ).fetchall()
        for r in reviewers:
            usernames.add(r['reviewer_username'])

        commenters = conn.execute(
            "SELECT DISTINCT reviewer_username FROM pr_review_comments "
            "WHERE pr_window_id = ?",
            (pr_window_id,)
        ).fetchall()
        for c in commenters:
            usernames.add(c['reviewer_username'])

        conn.close()
        return list(usernames)

    # ------------------------------------------------------------------
    # Skill delta recording (called after LLM profile generation)
    # ------------------------------------------------------------------

    def record_skill_deltas(self, pr_window_id: int, username: str,
                            repo_name: str,
                            skill_deltas: Dict[str, int]) -> None:
        """
        After the LLM generates/updates a profile for a user based on
        a specific PR, record the skill deltas so they can be subtracted
        on eviction.

        Also updates user_skills table with the new frequencies.
        """
        conn = self.db.connect()
        try:
            # Update the contribution row with skill deltas
            conn.execute("""
                UPDATE pr_user_contributions
                SET skill_deltas = ?
                WHERE pr_window_id = ? AND username = ? AND repo_name = ?
            """, (json.dumps(skill_deltas), pr_window_id, username, repo_name))

            # Upsert into user_skills
            for skill_name, delta in skill_deltas.items():
                existing = conn.execute(
                    "SELECT frequency FROM user_skills "
                    "WHERE username = ? AND repo_name = ? AND skill_name = ?",
                    (username, repo_name, skill_name)
                ).fetchone()

                if existing:
                    conn.execute("""
                        UPDATE user_skills SET frequency = frequency + ?
                        WHERE username = ? AND repo_name = ? AND skill_name = ?
                    """, (delta, username, repo_name, skill_name))
                else:
                    conn.execute("""
                        INSERT INTO user_skills (username, repo_name, skill_name, frequency)
                        VALUES (?, ?, ?, ?)
                    """, (username, repo_name, skill_name, delta))

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to record skill deltas for {username}: {e}")
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Assignment tracking (kept from old system)
    # ------------------------------------------------------------------

    def track_assignment(self, pr_number: int, repo_name: str,
                         pr_author: str, suggested_reviewers: List[str],
                         confidence_score: float) -> None:
        conn = self.db.connect()
        conn.execute("""
            INSERT INTO assignment_history (
                pr_number, repo_name, pr_author,
                suggested_reviewers, confidence_score
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            pr_number, repo_name, pr_author,
            json.dumps(suggested_reviewers), confidence_score
        ))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Bulk population (initial setup)
    # ------------------------------------------------------------------

    def populate_window(self, repo_name: str,
                        pr_list: List[Dict]) -> int:
        """
        Populate the window with a batch of PRs (initial setup).
        PRs should be ordered oldest-first (ascending by merged_at).
        Only the latest max_window_size PRs are kept.

        Each item in pr_list should have:
            pr_data: dict, reviews: list, review_comments: list

        Returns:
            Number of PRs added.
        """
        # Take only the latest max_window_size
        if len(pr_list) > self.max_window_size:
            pr_list = pr_list[-self.max_window_size:]

        added = 0
        for item in pr_list:
            pr_data = item['pr_data']
            reviews = item.get('reviews', [])
            review_comments = item.get('review_comments', [])

            result = self.add_pr(pr_data, reviews, review_comments)
            if result is not None:
                added += 1

        logger.info(f"Populated window for {repo_name}: {added} PRs added")
        return added
