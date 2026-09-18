"""
Unified Profile Builder — Phase 3 of the rolling window refactor.

Generates and updates user profiles (reviewer + developer combined)
using LLM analysis against the rolling window of PRs in SQLite.

Two modes:
  - Full generation: analyze ALL window activity for a user (initial setup)
  - Incremental update: analyze a SINGLE merged PR's contribution (on merge)
"""

import json
from typing import Dict, List, Optional

from src.profile_generator.llm_client import LLMClient
from src.profile_generator.prompt_builder import PromptBuilder
from src.profile_generator.skill_analyzer import SkillAnalyzer
from src.storage.window_manager import WindowManager
from src.utils import get_logger, get_config

logger = get_logger(__name__)


class UnifiedProfileBuilder:
    """Builds unified user profiles from the rolling window using LLM."""

    def __init__(self, window_manager: Optional[WindowManager] = None,
                 llm_client: Optional[LLMClient] = None):
        self.wm = window_manager or WindowManager()
        self.llm = llm_client or LLMClient()
        self.skill_analyzer = SkillAnalyzer()
        self.prompt_builder = PromptBuilder()
        self.config = get_config()
        logger.info("Unified Profile Builder initialized")

    # ------------------------------------------------------------------
    # Data gathering from the rolling window
    # ------------------------------------------------------------------

    def gather_user_activity(self, username: str, repo_name: str) -> Dict:
        """Gather all activity for a user from the rolling window."""
        return {
            'username': username,
            'repo_name': repo_name,
            'authored_prs': self.wm.get_user_authored_prs(username, repo_name),
            'reviews': self.wm.get_user_reviews(username, repo_name),
            'review_comments': self.wm.get_user_review_comments(username, repo_name),
            'profile_stats': self.wm.get_user_profile(username, repo_name),
        }

    def gather_pr_activity_for_user(self, pr_window_id: int,
                                     username: str,
                                     repo_name: str) -> Optional[Dict]:
        """Gather a single PR's data relevant to a specific user."""
        pr = self.wm.get_pr_by_id(pr_window_id)
        if not pr:
            return None

        pr_reviews = self.wm.get_pr_reviews(pr_window_id)
        pr_comments = self.wm.get_pr_review_comments(pr_window_id)

        return {
            'pr': pr,
            'is_author': pr['author_username'] == username,
            'user_reviews': [r for r in pr_reviews
                             if r['reviewer_username'] == username],
            'user_comments': [c for c in pr_comments
                              if c['reviewer_username'] == username],
        }

    # ------------------------------------------------------------------
    # Activity summary builders (prepare data for LLM)
    # ------------------------------------------------------------------

    def _build_activity_summary(self, activity: Dict,
                                max_items: int = 20) -> List[Dict]:
        """Build a summarized activity list from all window data."""
        items = []

        for pr in activity.get('authored_prs', [])[:max_items]:
            items.append(self._summarize_authored_pr(pr))

        for review in activity.get('reviews', [])[:max_items]:
            items.append({
                'role': 'reviewer',
                'pr_title': (review.get('pr_title') or '')[:100],
                'repo': review.get('repo_name', ''),
                'review_state': review.get('review_state', ''),
                'review_comment': (review.get('review_body') or '')[:300],
            })

        for comment in activity.get('review_comments', [])[:max_items]:
            items.append({
                'role': 'commenter',
                'file_path': comment.get('file_path', ''),
                'comment': (comment.get('body') or '')[:300],
                'repo': comment.get('repo_name', ''),
            })

        return items[:max_items * 2]

    def _build_pr_summary(self, pr_activity: Dict) -> List[Dict]:
        """Build a summary of a single PR's activity for a user."""
        items = []
        pr = pr_activity['pr']

        if pr_activity['is_author']:
            items.append(self._summarize_authored_pr(pr))

        for review in pr_activity.get('user_reviews', []):
            items.append({
                'role': 'reviewer',
                'pr_title': (pr.get('title') or '')[:100],
                'repo': pr.get('repo_name', ''),
                'review_state': review.get('review_state', ''),
                'review_comment': (review.get('review_body') or '')[:300],
            })

        for comment in pr_activity.get('user_comments', []):
            items.append({
                'role': 'commenter',
                'file_path': comment.get('file_path', ''),
                'comment': (comment.get('body') or '')[:300],
                'repo': comment.get('repo_name', ''),
            })

        return items

    def _summarize_authored_pr(self, pr: Dict) -> Dict:
        """Create a summary dict for an authored PR."""
        changed_files = self._parse_json_field(pr.get('changed_files', '[]'))
        labels = self._parse_json_field(pr.get('labels', '[]'))

        return {
            'role': 'author',
            'pr_title': (pr.get('title') or '')[:100],
            'pr_description': (pr.get('description') or '')[:300],
            'repo': pr.get('repo_name', ''),
            'additions': pr.get('additions', 0),
            'deletions': pr.get('deletions', 0),
            'files_changed': pr.get('changed_files_count', 0),
            'changed_files': changed_files[:10],
            'labels': labels,
        }

    @staticmethod
    def _parse_json_field(value) -> list:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------

    def _analyze_skills(self, username: str,
                        activity_data: List[Dict]) -> str:
        """LLM Step 1: analyze activity and extract JS skills."""
        template = self.llm.load_prompt_template('unified_skills_analysis.txt')
        variables = {
            'username': username,
            'activity_data': json.dumps(activity_data, indent=2),
        }
        return self.llm.generate(template, variables)

    def _generate_profile(self, username: str, skills_analysis: str,
                          stats: Dict) -> Optional[Dict]:
        """LLM Step 2: generate javascript_skill_matrix profile."""
        from langchain.output_parsers import PydanticOutputParser
        from src.profile_generator.reviewer_profile_builder import ReviewerProfile

        parser = PydanticOutputParser(pydantic_object=ReviewerProfile)
        format_instructions = parser.get_format_instructions()

        repo_name = stats.get('repo_name', '')
        total_activity = (stats.get('total_reviews', 0)
                          + stats.get('total_prs_authored', 0))

        variables = self.prompt_builder.build_profile_generation_variables(
            reviewer_name=username,
            skills_analysis=skills_analysis,
            review_count=total_activity,
            repo_list=repo_name,
            format_instructions=format_instructions,
        )

        template = self.llm.load_prompt_template('reviewer_profile_generation.txt')

        try:
            profile_result = self.llm.generate(
                template, variables, parse_json=True
            )

            profile = ReviewerProfile(**profile_result)
            profile_dict = profile.dict()

            is_valid, errors = self.skill_analyzer.validate_skill_matrix(
                profile_dict['javascript_skill_matrix']
            )
            if not is_valid:
                logger.warning(
                    f"Profile validation failed for {username}, auto-fixing..."
                )
                fixed = self.skill_analyzer.fix_skill_matrix(
                    profile_dict['javascript_skill_matrix']
                )
                profile_dict['javascript_skill_matrix'] = fixed

            if not profile_dict.get('primary_skills'):
                primary = self.skill_analyzer.extract_primary_skills(
                    profile_dict['javascript_skill_matrix'], min_frequency=3
                )
                profile_dict['primary_skills'] = primary[:5]

            return profile_dict

        except Exception as e:
            logger.error(f"Failed to generate profile for {username}: {e}")
            return None

    # ------------------------------------------------------------------
    # Skill matrix helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_skill_deltas(skill_matrix: Dict) -> Dict[str, int]:
        """Extract flat {skill_name: frequency} from a javascript_skill_matrix."""
        deltas = {}
        for skills in skill_matrix.values():
            for skill in (skills or []):
                if ', frequency:' in skill:
                    parts = skill.split(', frequency:')
                    name = parts[0].strip()
                    try:
                        freq = int(parts[1].strip())
                        deltas[name] = deltas.get(name, 0) + freq
                    except (ValueError, IndexError):
                        continue
        return deltas

    @staticmethod
    def _parse_skill_matrix(matrix: Dict) -> Dict[str, Dict[str, int]]:
        """Parse embedded-frequency matrix into {category: {skill: freq}}."""
        result = {}
        for category_key, skills in matrix.items():
            base = category_key.split(', frequency:')[0].strip()
            skill_dict = {}
            for skill in (skills or []):
                if ', frequency:' in skill:
                    parts = skill.split(', frequency:')
                    try:
                        skill_dict[parts[0].strip()] = int(parts[1].strip())
                    except (ValueError, IndexError):
                        pass
            result[base] = skill_dict
        return result

    @staticmethod
    def _build_skill_matrix(parsed: Dict[str, Dict[str, int]]) -> Dict:
        """Rebuild embedded-frequency format from parsed data."""
        matrix = {}
        for category, skills in parsed.items():
            if skills:
                total = sum(skills.values())
                key = f"{category}, frequency: {total}"
                matrix[key] = [
                    f"{name}, frequency: {freq}"
                    for name, freq in skills.items()
                ]
            else:
                matrix[category] = []
        return matrix

    def _merge_skill_matrices(self, existing: Dict, new: Dict) -> Dict:
        """Merge two javascript_skill_matrix dicts by adding frequencies."""
        existing_parsed = self._parse_skill_matrix(existing)
        new_parsed = self._parse_skill_matrix(new)

        merged = {}
        for cat in set(list(existing_parsed) + list(new_parsed)):
            combined = dict(existing_parsed.get(cat, {}))
            for skill, freq in new_parsed.get(cat, {}).items():
                combined[skill] = combined.get(skill, 0) + freq
            merged[cat] = combined

        return self._build_skill_matrix(merged)

    # ------------------------------------------------------------------
    # Database persistence
    # ------------------------------------------------------------------

    def _save_profile_to_db(self, username: str, repo_name: str,
                             profile: Dict) -> None:
        """Save LLM-generated profile fields to user_profiles."""
        conn = self.wm.db.connect()
        try:
            conn.execute("""
                UPDATE user_profiles SET
                    experience_level = ?,
                    primary_skills = ?,
                    programming_languages = ?,
                    summary = ?,
                    javascript_skill_matrix = ?,
                    profile_json = ?,
                    updated_at = datetime('now')
                WHERE username = ? AND repo_name = ?
            """, (
                profile.get('experience_level', ''),
                json.dumps(profile.get('primary_skills', [])),
                json.dumps(profile.get('programming_languages', [])),
                profile.get('summary', ''),
                json.dumps(profile.get('javascript_skill_matrix', {})),
                json.dumps(profile),
                username, repo_name,
            ))
            conn.commit()
        finally:
            conn.close()

    def _replace_user_skills(self, username: str, repo_name: str,
                              skill_deltas: Dict[str, int]) -> None:
        """Replace all user_skills rows with new data (full regen)."""
        conn = self.wm.db.connect()
        try:
            conn.execute(
                "DELETE FROM user_skills WHERE username = ? AND repo_name = ?",
                (username, repo_name)
            )
            for skill_name, freq in skill_deltas.items():
                conn.execute("""
                    INSERT INTO user_skills
                        (username, repo_name, skill_name, frequency)
                    VALUES (?, ?, ?, ?)
                """, (username, repo_name, skill_name, freq))
            conn.commit()
        finally:
            conn.close()

    def _merge_profile_to_db(self, username: str, repo_name: str,
                              new_profile: Dict) -> None:
        """Merge a new profile analysis into the existing profile."""
        conn = self.wm.db.connect()
        try:
            existing = conn.execute(
                "SELECT javascript_skill_matrix FROM user_profiles "
                "WHERE username = ? AND repo_name = ?",
                (username, repo_name)
            ).fetchone()

            existing_matrix = {}
            if existing and existing['javascript_skill_matrix']:
                try:
                    existing_matrix = json.loads(
                        existing['javascript_skill_matrix']
                    )
                except (json.JSONDecodeError, TypeError):
                    pass

            merged = self._merge_skill_matrices(
                existing_matrix,
                new_profile.get('javascript_skill_matrix', {})
            )

            conn.execute("""
                UPDATE user_profiles SET
                    experience_level = ?,
                    primary_skills = ?,
                    programming_languages = ?,
                    summary = ?,
                    javascript_skill_matrix = ?,
                    profile_json = ?,
                    updated_at = datetime('now')
                WHERE username = ? AND repo_name = ?
            """, (
                new_profile.get('experience_level', ''),
                json.dumps(new_profile.get('primary_skills', [])),
                json.dumps(new_profile.get('programming_languages', [])),
                new_profile.get('summary', ''),
                json.dumps(merged),
                json.dumps(new_profile),
                username, repo_name,
            ))
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Public API: Full profile generation (initial setup)
    # ------------------------------------------------------------------

    def generate_full_profile(self, username: str,
                              repo_name: str) -> Optional[Dict]:
        """
        Generate a complete profile from ALL window activity.
        Used during initial setup. Does NOT record per-PR skill
        deltas (too expensive for 500 PRs).
        """
        logger.info(f"Generating full profile for {username} in {repo_name}")

        activity = self.gather_user_activity(username, repo_name)
        stats = activity['profile_stats']
        if not stats:
            logger.warning(f"No profile stats for {username}")
            return None

        activity_summary = self._build_activity_summary(activity)
        if not activity_summary:
            logger.warning(f"No activity data for {username}")
            return None

        skills_analysis = self._analyze_skills(username, activity_summary)
        profile = self._generate_profile(username, skills_analysis, stats)
        if not profile:
            return None

        self._save_profile_to_db(username, repo_name, profile)

        skill_deltas = self._extract_skill_deltas(
            profile.get('javascript_skill_matrix', {})
        )
        if skill_deltas:
            self._replace_user_skills(username, repo_name, skill_deltas)

        logger.info(
            f"Profile generated for {username}: "
            f"{profile.get('experience_level')}, "
            f"{len(skill_deltas)} skills"
        )
        return profile

    def generate_all_profiles(self, repo_name: str) -> Dict[str, bool]:
        """
        Generate profiles for ALL users in the window.
        Returns {username: success}.
        """
        users = self.wm.get_all_users(repo_name, include_developers=True)
        results = {}

        logger.info(
            f"Generating profiles for {len(users)} users in {repo_name}"
        )

        for user in users:
            username = user['username']
            try:
                profile = self.generate_full_profile(username, repo_name)
                results[username] = profile is not None
            except Exception as e:
                logger.error(
                    f"Failed to generate profile for {username}: {e}"
                )
                results[username] = False

        succeeded = sum(1 for v in results.values() if v)
        logger.info(
            f"Profile generation complete: {succeeded}/{len(users)} succeeded"
        )
        return results

    # ------------------------------------------------------------------
    # Public API: Incremental update (on PR merge)
    # ------------------------------------------------------------------

    def update_profile_for_pr(self, pr_window_id: int, username: str,
                              repo_name: str) -> Optional[Dict[str, int]]:
        """
        Update a user's profile based on a single newly merged PR.
        Records skill_deltas for subtract-on-eviction.

        Returns the skill_deltas recorded, or None on failure.
        """
        logger.info(
            f"Updating profile for {username} "
            f"(PR window_id={pr_window_id})"
        )

        pr_activity = self.gather_pr_activity_for_user(
            pr_window_id, username, repo_name
        )
        if not pr_activity:
            return None

        pr_summary = self._build_pr_summary(pr_activity)
        if not pr_summary:
            return None

        skills_analysis = self._analyze_skills(username, pr_summary)

        stats = self.wm.get_user_profile(username, repo_name) or {}
        profile = self._generate_profile(username, skills_analysis, stats)
        if not profile:
            return None

        skill_deltas = self._extract_skill_deltas(
            profile.get('javascript_skill_matrix', {})
        )

        if skill_deltas:
            self.wm.record_skill_deltas(
                pr_window_id, username, repo_name, skill_deltas
            )

        self._merge_profile_to_db(username, repo_name, profile)

        logger.info(
            f"Profile updated for {username}: "
            f"{len(skill_deltas)} skill deltas recorded"
        )
        return skill_deltas

    def update_profiles_for_merged_pr(self, pr_window_id: int,
                                       repo_name: str) -> Dict[str, bool]:
        """
        Update profiles for ALL users involved in a merged PR.
        Called after add_pr() on the merge webhook.

        Returns {username: success}.
        """
        involved = self.wm.get_involved_users(pr_window_id)
        results = {}

        logger.info(
            f"Updating profiles for {len(involved)} users "
            f"from PR (window_id={pr_window_id})"
        )

        for username in involved:
            try:
                deltas = self.update_profile_for_pr(
                    pr_window_id, username, repo_name
                )
                results[username] = deltas is not None
            except Exception as e:
                logger.error(
                    f"Failed to update profile for {username}: {e}"
                )
                results[username] = False

        return results
