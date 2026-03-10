"""
GitHub API Client
Wrapper for GitHub API with authentication, rate limiting, and error handling
"""

import time
import urllib.request
import urllib.parse
import json
import jwt
import os
from typing import Dict, List, Optional, Any
from datetime import datetime

from src.utils import get_logger, retry_on_failure, rate_limit, get_config

logger = get_logger(__name__)


class GitHubClient:
    """GitHub API client with authentication (App or Personal Token) and rate limiting"""
    
    def __init__(self, api_token: Optional[str] = None, installation_id: Optional[int] = None):
        """
        Initialize GitHub API client
        
        Args:
            api_token: GitHub personal access token (optional)
            installation_id: GitHub App installation ID (for app auth)
        """
        self.config = get_config()
        self.base_url = "https://api.github.com"
        self.installation_id = installation_id
        
        # Priority:
        # 1. Direct api_token passed to constructor
        # 2. installation_id (will generate token via App ID + Private Key)
        # 3. GITHUB_TOKEN environment variable
        
        self.api_token = api_token or os.getenv('GITHUB_TOKEN')
        self.app_id = os.getenv('GITHUB_APP_ID')
        # Support both: full key content (Railway) or file path (local)
        self.private_key = os.getenv('GITHUB_PRIVATE_KEY') or self._read_key_from_path()

        if not self.api_token and self.installation_id and self.app_id and self.private_key:
            self._refresh_installation_token()
        
        if not self.api_token:
            logger.warning("⚠️ No GitHub token or App credentials provided. Client may fail.")
        
        # Rate limiting settings from config
        self.rate_limit_delay = self.config.get('github.api_rate_limit_delay', 0.3)
        
        logger.info(f"✅ GitHub API client initialized (Auth: {'App' if self.installation_id else 'Token'})")

    def _read_key_from_path(self) -> Optional[str]:
        """Fallback: read private key from file path (for local dev)"""
        path = os.getenv('GITHUB_PRIVATE_KEY_PATH')
        if path:
            try:
                with open(path, 'r') as f:
                    return f.read()
            except Exception:
                pass
        return None

    def _refresh_installation_token(self):
        """Exchange App JWT for an installation-specific access token"""
        try:
            # Generate JWT using private key content
            now = int(time.time())
            payload = {
                'iat': now - 60,
                'exp': now + (10 * 60),
                'iss': self.app_id
            }
            app_jwt = jwt.encode(payload, self.private_key, algorithm='RS256')

            # Exchange JWT for installation token
            url = f"{self.base_url}/app/installations/{self.installation_id}/access_tokens"
            req = urllib.request.Request(url, method='POST')
            req.add_header('Authorization', f'Bearer {app_jwt}')
            req.add_header('Accept', 'application/vnd.github+json')
            
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode('utf-8'))
                self.api_token = data['token']
                logger.info(f"🔑 Got installation token for ID: {self.installation_id}")
                
        except Exception as e:
            logger.error(f"❌ Failed to refresh installation token: {e}")
            raise
    
    @retry_on_failure(max_attempts=3, delay=2.0, backoff=2.0)
    @rate_limit(calls_per_second=3.0)  # GitHub allows ~5000 requests/hour
    def _make_request(self, url: str, method: str = "GET") -> Optional[Dict]:
        """
        Make authenticated request to GitHub API
        
        Args:
            url: Full API URL
            method: HTTP method (GET, POST, etc.)
        
        Returns:
            JSON response as dictionary, or None on failure
        """
        req = urllib.request.Request(url, method=method)
        req.add_header('Authorization', f'Bearer {self.api_token}')
        req.add_header('User-Agent', 'GitHub-Reviewer-AI/1.0')
        req.add_header('Accept', 'application/vnd.github+json')
        req.add_header('X-GitHub-Api-Version', '2022-11-28')
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                # Check rate limit headers
                remaining = response.headers.get('X-RateLimit-Remaining')
                if remaining and int(remaining) < 100:
                    logger.warning(f"⚠️ GitHub API rate limit low: {remaining} requests remaining")
                
                return data
                
        except urllib.error.HTTPError as e:
            if e.code == 403:
                logger.error("❌ GitHub API rate limit exceeded or token invalid")
            elif e.code == 404:
                logger.warning(f"⚠️ Resource not found: {url}")
            else:
                logger.error(f"❌ HTTP error {e.code}: {e.reason}")
            return None
            
        except urllib.error.URLError as e:
            logger.error(f"❌ Network error: {e.reason}")
            return None
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON response: {e}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            return None
    
    def get_repository(self, owner: str, repo: str) -> Optional[Dict]:
        """
        Get repository information
        
        Args:
            owner: Repository owner
            repo: Repository name
        
        Returns:
            Repository data or None
        """
        url = f"{self.base_url}/repos/{owner}/{repo}"
        logger.info(f"📦 Fetching repository: {owner}/{repo}")
        return self._make_request(url)
    
    def get_pull_requests(
        self,
        owner: str,
        repo: str,
        state: str = "all",
        per_page: int = 30,
        page: int = 1,
        sort: str = "updated",
        direction: str = "desc"
    ) -> Optional[List[Dict]]:
        """
        Get pull requests from repository
        
        Args:
            owner: Repository owner
            repo: Repository name
            state: PR state (open, closed, all)
            per_page: Results per page (max 100)
            page: Page number
            sort: Sort by (created, updated, popularity, long-running)
            direction: Sort direction (asc, desc)
        
        Returns:
            List of PR data or None
        """
        params = urllib.parse.urlencode({
            'state': state,
            'per_page': min(per_page, 100),
            'page': page,
            'sort': sort,
            'direction': direction
        })
        
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls?{params}"
        
        logger.debug(f"📄 Fetching PRs: page {page}, per_page {per_page}")
        return self._make_request(url)
    
    def get_pull_request(self, owner: str, repo: str, pr_number: int) -> Optional[Dict]:
        """
        Get single pull request details
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
        
        Returns:
            PR data or None
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        logger.debug(f"📋 Fetching PR #{pr_number}")
        return self._make_request(url)
    
    def get_pr_reviews(self, owner: str, repo: str, pr_number: int) -> Optional[List[Dict]]:
        """
        Get all reviews for a PR
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
        
        Returns:
            List of review data or None
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        logger.debug(f"💬 Fetching reviews for PR #{pr_number}")
        
        reviews = self._make_request(url)
        
        if not reviews:
            return []
        
        # Filter out reviews with deleted/unavailable users
        valid_reviews = []
        for review in reviews:
            if review.get('user') is None:
                logger.debug(f"⚠️ Skipping review {review['id']} - user unavailable")
                continue
            valid_reviews.append(review)
        
        return valid_reviews
    
    def get_pr_review_comments(self, owner: str, repo: str, pr_number: int) -> Optional[List[Dict]]:
        """
        Get review comments (line-by-line comments) for a PR
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
        
        Returns:
            List of review comment data or None
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/comments"
        logger.debug(f"💭 Fetching review comments for PR #{pr_number}")
        
        comments = self._make_request(url)
        
        if not comments:
            return []
        
        # Filter out comments with deleted/unavailable users
        valid_comments = []
        for comment in comments:
            if comment.get('user') is None:
                logger.debug(f"⚠️ Skipping comment {comment['id']} - user unavailable")
                continue
            valid_comments.append(comment)
        
        return valid_comments
    
    def get_pr_comments(self, owner: str, repo: str, pr_number: int) -> Optional[List[Dict]]:
        """
        Get general issue comments on a PR
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number (same as issue number)
        
        Returns:
            List of comment data or None
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        logger.debug(f"💬 Fetching general comments for PR #{pr_number}")
        
        comments = self._make_request(url)
        
        if not comments:
            return []
        
        # Filter out comments with deleted/unavailable users
        valid_comments = []
        for comment in comments:
            if comment.get('user') is None:
                logger.debug(f"⚠️ Skipping comment {comment['id']} - user unavailable")
                continue
            valid_comments.append(comment)
        
        return valid_comments
    
    def get_pr_files(self, owner: str, repo: str, pr_number: int) -> Optional[List[Dict]]:
        """
        Get files changed in a PR
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
        
        Returns:
            List of file data or None
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        logger.debug(f"📁 Fetching files for PR #{pr_number}")
        return self._make_request(url)
    
    def post_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        comment_body: str
    ) -> Optional[Dict]:
        """
        Post a comment on a PR
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
            comment_body: Comment text (supports Markdown)
        
        Returns:
            Created comment data or None
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        
        data = json.dumps({'body': comment_body}).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Authorization', f'Bearer {self.api_token}')
        req.add_header('User-Agent', 'GitHub-Reviewer-AI/1.0')
        req.add_header('Accept', 'application/vnd.github+json')
        req.add_header('Content-Type', 'application/json')
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                logger.info(f"✅ Posted comment on PR #{pr_number}")
                return result
        except Exception as e:
            logger.error(f"❌ Failed to post comment on PR #{pr_number}: {e}")
            return None
    
    def request_reviewers(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        reviewers: List[str]
    ) -> Optional[Dict]:
        """
        Request reviewers for a PR
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
            reviewers: List of GitHub usernames to request as reviewers
        
        Returns:
            Response data or None
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers"
        
        data = json.dumps({'reviewers': reviewers}).encode('utf-8')
        
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Authorization', f'Bearer {self.api_token}')
        req.add_header('User-Agent', 'GitHub-Reviewer-AI/1.0')
        req.add_header('Accept', 'application/vnd.github+json')
        req.add_header('Content-Type', 'application/json')
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                logger.info(f"✅ Requested reviewers for PR #{pr_number}: {reviewers}")
                return result
        except Exception as e:
            logger.error(f"❌ Failed to request reviewers for PR #{pr_number}: {e}")
            return None


# Example usage and testing
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("🔌 Testing GitHub Client")
    print("=" * 60)
    
    # Initialize client
    client = GitHubClient()
    
    # Test repository access
    repo = client.get_repository('moment', 'moment')
    if repo:
        print(f"✅ Repository: {repo['full_name']}")
        print(f"   Stars: {repo['stargazers_count']}")
        print(f"   Forks: {repo['forks_count']}")
    
    # Test PR fetching
    prs = client.get_pull_requests('moment', 'moment', per_page=5)
    if prs:
        print(f"\n✅ Fetched {len(prs)} PRs")
        for pr in prs[:3]:
            print(f"   PR #{pr['number']}: {pr['title'][:50]}")
    
    print("\n✅ GitHub client working correctly!")