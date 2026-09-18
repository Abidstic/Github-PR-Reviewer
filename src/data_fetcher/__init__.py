"""
Data fetching modules for GitHub Reviewer AI.

Phase 6: ReviewerDataFetcher is no longer used (replaced by direct
GitHubClient calls + WindowManager.populate_window).  Kept on disk
for reference but not imported here.
"""

from src.data_fetcher.github_client import GitHubClient

__all__ = [
    'GitHubClient',
]
