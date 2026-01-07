"""
GitHub Poster
Posts reviewer suggestions to GitHub PRs as comments
"""

import os
from typing import Dict, Optional
from github import Github, GithubException

from src.utils import get_logger, get_config

logger = get_logger(__name__)


class GitHubPoster:
    """Posts suggestions to GitHub PRs"""
    
    def __init__(self, github_token: Optional[str] = None):
        """
        Initialize GitHub poster
        
        Args:
            github_token: GitHub personal access token (from .env if not provided)
        """
        self.config = get_config()
        
        # Get GitHub token
        if github_token is None:
            github_token = os.getenv('GITHUB_TOKEN')
        
        if not github_token:
            raise ValueError(
                "GitHub token not provided. "
                "Set GITHUB_TOKEN in .env or pass github_token parameter"
            )
        
        # Initialize GitHub client
        self.github = Github(github_token)
        
        # Test connection
        try:
            user = self.github.get_user()
            logger.info(f"✅ GitHub poster initialized (authenticated as: {user.login})")
        except GithubException as e:
            logger.error(f"❌ GitHub authentication failed: {e}")
            raise
    
    def post_suggestion_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        comment_body: str,
        dry_run: bool = False
    ) -> bool:
        """
        Post suggestion comment to PR
        
        Args:
            repo_full_name: Repository name (e.g., 'moment/moment')
            pr_number: PR number
            comment_body: Markdown comment text
            dry_run: If True, only simulate posting (for testing)
        
        Returns:
            Success boolean
        """
        logger.info(f"💬 Posting suggestion to {repo_full_name} PR #{pr_number}")
        
        if dry_run:
            logger.info("🧪 DRY RUN MODE - Not actually posting to GitHub")
            logger.debug(f"Would post comment:\n{comment_body[:200]}...")
            return True
        
        try:
            # Get repository
            repo = self.github.get_repo(repo_full_name)
            
            # Get pull request
            pr = repo.get_pull(pr_number)
            
            # Post comment
            comment = pr.create_issue_comment(comment_body)
            
            logger.info(f"✅ Posted comment (ID: {comment.id}) to PR #{pr_number}")
            return True
            
        except GithubException as e:
            logger.error(f"❌ Failed to post comment: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error posting comment: {e}")
            return False
    
    def check_if_already_commented(
        self,
        repo_full_name: str,
        pr_number: int,
        bot_identifier: str = "🤖 AI-Powered Reviewer Suggestions"
    ) -> bool:
        """
        Check if bot has already commented on this PR
        
        Args:
            repo_full_name: Repository name
            pr_number: PR number
            bot_identifier: Unique string to identify bot comments
        
        Returns:
            True if already commented, False otherwise
        """
        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            
            # Get all comments
            comments = pr.get_issue_comments()
            
            # Check if bot has already commented
            for comment in comments:
                if bot_identifier in comment.body:
                    logger.info(f"ℹ️ Bot has already commented on PR #{pr_number}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ Failed to check existing comments: {e}")
            return False
    
    def update_existing_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        comment_body: str,
        bot_identifier: str = "🤖 AI-Powered Reviewer Suggestions",
        dry_run: bool = False
    ) -> bool:
        """
        Update existing bot comment (or create new if not exists)
        
        Args:
            repo_full_name: Repository name
            pr_number: PR number
            comment_body: New comment text
            bot_identifier: Unique string to identify bot comments
            dry_run: If True, only simulate updating
        
        Returns:
            Success boolean
        """
        logger.info(f"🔄 Updating suggestion for {repo_full_name} PR #{pr_number}")
        
        if dry_run:
            logger.info("🧪 DRY RUN MODE - Not actually updating GitHub")
            return True
        
        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            
            # Find existing bot comment
            comments = pr.get_issue_comments()
            bot_comment = None
            
            for comment in comments:
                if bot_identifier in comment.body:
                    bot_comment = comment
                    break
            
            if bot_comment:
                # Update existing comment
                bot_comment.edit(comment_body)
                logger.info(f"✅ Updated existing comment (ID: {bot_comment.id})")
            else:
                # Create new comment
                comment = pr.create_issue_comment(comment_body)
                logger.info(f"✅ Created new comment (ID: {comment.id})")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update comment: {e}")
            return False
    
    def request_reviewers(
        self,
        repo_full_name: str,
        pr_number: int,
        reviewer_usernames: list,
        dry_run: bool = False
    ) -> bool:
        """
        Actually request reviewers on the PR (not just comment)
        
        Args:
            repo_full_name: Repository name
            pr_number: PR number
            reviewer_usernames: List of GitHub usernames to request
            dry_run: If True, only simulate requesting
        
        Returns:
            Success boolean
        """
        logger.info(f"👥 Requesting reviewers for {repo_full_name} PR #{pr_number}")
        
        if dry_run:
            logger.info(f"🧪 DRY RUN MODE - Would request: {', '.join(reviewer_usernames)}")
            return True
        
        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            
            # Request reviewers
            pr.create_review_request(reviewers=reviewer_usernames)
            
            logger.info(f"✅ Requested reviewers: {', '.join(reviewer_usernames)}")
            return True
            
        except GithubException as e:
            logger.error(f"❌ Failed to request reviewers: {e}")
            logger.warning("Note: You may need additional permissions to request reviewers")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error requesting reviewers: {e}")
            return False
    
    def get_pr_data(self, repo_full_name: str, pr_number: int) -> Optional[Dict]:
        """
        Fetch PR data from GitHub
        
        Args:
            repo_full_name: Repository name
            pr_number: PR number
        
        Returns:
            PR data dictionary or None
        """
        try:
            repo = self.github.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            
            # Build PR data
            pr_data = {
                'pr_number': pr.number,
                'title': pr.title,
                'description': pr.body or '',
                'author': {
                    'username': pr.user.login
                },
                'repo_name': repo_full_name,
                'changed_files': [f.filename for f in pr.get_files()],
                'additions': pr.additions,
                'deletions': pr.deletions,
                'labels': [label.name for label in pr.labels],
                'state': pr.state,
                'created_at': pr.created_at.isoformat()
            }
            
            logger.info(f"✅ Fetched PR #{pr_number} data")
            return pr_data
            
        except Exception as e:
            logger.error(f"❌ Failed to fetch PR data: {e}")
            return None


# Example usage and testing
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("💬 Testing GitHub Poster")
    print("=" * 60)
    
    try:
        # Initialize poster
        poster = GitHubPoster()
        print("✅ GitHub poster initialized")
        
        # Test getting PR data (use a real PR for testing)
        print("\n📊 Testing PR data fetch...")
        print("Note: Change repo/PR number to test with a real PR")
        
        # Sample comment
        sample_comment = """
## 🤖 AI-Powered Reviewer Suggestions

**Pull Request:** #1234 - Test PR
**Confidence:** 🟢 High

### 👥 Recommended Reviewers

1. **@reviewer1** (85% match)
   - High frequency in Express.js (10x)
   - Senior experience matches complexity

_🤖 This is a test comment from GitHub Reviewer AI_
"""
        
        # DRY RUN - doesn't actually post
        print("\n🧪 Testing comment posting (DRY RUN)...")
        success = poster.post_suggestion_comment(
            repo_full_name='moment/moment',
            pr_number=9999,  # Fake PR number
            comment_body=sample_comment,
            dry_run=True  # Safe mode
        )
        
        if success:
            print("✅ Comment would be posted successfully (dry run)")
        
        print("\n✅ GitHub Poster working correctly!")
        print("\n⚠️ To test actual posting:")
        print("   1. Create a test repository")
        print("   2. Create a test PR")
        print("   3. Change dry_run=False")
        print("   4. Update repo_full_name and pr_number")
        
    except ValueError as e:
        print(f"⚠️ Configuration error: {e}")
        print("Make sure GITHUB_TOKEN is set in .env file")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()