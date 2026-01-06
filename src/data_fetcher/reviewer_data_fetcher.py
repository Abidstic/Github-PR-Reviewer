"""
Reviewer Data Fetcher
Fetches PR review data from GitHub repositories
"""

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from src.data_fetcher.github_client import GitHubClient
from src.utils import get_logger, get_config, save_json, get_timestamp

logger = get_logger(__name__)


class ReviewerDataFetcher:
    """Fetches and structures reviewer data from GitHub"""
    
    def __init__(self, github_client: Optional[GitHubClient] = None):
        """
        Initialize reviewer data fetcher
        
        Args:
            github_client: GitHubClient instance (creates new one if None)
        """
        self.client = github_client or GitHubClient()
        self.config = get_config()
        
        # Settings from config
        self.max_prs = self.config.get('github.max_prs_to_fetch', 500)
        
        logger.info("✅ Reviewer data fetcher initialized")
    
    def fetch_pr_reviewer_data(self, owner: str, repo: str, pr_number: int) -> Optional[Dict]:
        """
        Fetch complete reviewer data for a single PR
        
        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: PR number
        
        Returns:
            Structured PR reviewer data or None
        """
        logger.info(f"📋 Fetching reviewer data for PR #{pr_number}")
        
        # Get PR details
        pr = self.client.get_pull_request(owner, repo, pr_number)
        if not pr:
            logger.warning(f"⚠️ Could not fetch PR #{pr_number}")
            return None
        
        # Get reviews
        reviews = self.client.get_pr_reviews(owner, repo, pr_number)
        
        # Get review comments
        review_comments = self.client.get_pr_review_comments(owner, repo, pr_number)
        
        # Get general comments
        general_comments = self.client.get_pr_comments(owner, repo, pr_number)
        
        # Structure the data
        pr_reviewer_data = self._structure_pr_data(
            pr, reviews, review_comments, general_comments
        )
        
        logger.debug(
            f"✅ PR #{pr_number}: {len(reviews)} reviews, "
            f"{len(review_comments)} review comments, "
            f"{len(general_comments)} general comments"
        )
        
        return pr_reviewer_data
    
    def _structure_pr_data(
        self,
        pr: Dict,
        reviews: List[Dict],
        review_comments: List[Dict],
        general_comments: List[Dict]
    ) -> Dict:
        """Structure PR data with reviewer information"""
        
        # Extract reviews
        structured_reviews = []
        for review in reviews:
            review_info = {
                "review_id": review['id'],
                "reviewer_username": review['user']['login'],
                "reviewer_id": review['user']['id'],
                "reviewer_profile_url": review['user']['html_url'],
                "reviewer_avatar_url": review['user']['avatar_url'],
                "reviewer_type": review['user']['type'],
                "state": review['state'],
                "body": review.get('body', ''),
                "submitted_at": review['submitted_at'],
                "commit_id": review.get('commit_id', ''),
                "html_url": review.get('html_url', ''),
                "author_association": review.get('author_association', '')
            }
            structured_reviews.append(review_info)
        
        # Extract review comments
        structured_review_comments = []
        for comment in review_comments:
            comment_info = {
                "comment_id": comment['id'],
                "reviewer_username": comment['user']['login'],
                "reviewer_id": comment['user']['id'],
                "reviewer_profile_url": comment['user']['html_url'],
                "body": comment.get('body', ''),
                "created_at": comment['created_at'],
                "updated_at": comment['updated_at'],
                "path": comment.get('path', ''),
                "line": comment.get('line'),
                "diff_hunk": comment.get('diff_hunk', ''),
                "html_url": comment.get('html_url', ''),
                "author_association": comment.get('author_association', ''),
                "in_reply_to_id": comment.get('in_reply_to_id')
            }
            structured_review_comments.append(comment_info)
        
        # Extract general comments
        structured_general_comments = []
        for comment in general_comments:
            comment_info = {
                "comment_id": comment['id'],
                "commenter_username": comment['user']['login'],
                "commenter_id": comment['user']['id'],
                "commenter_profile_url": comment['user']['html_url'],
                "body": comment.get('body', ''),
                "created_at": comment['created_at'],
                "updated_at": comment['updated_at'],
                "html_url": comment.get('html_url', ''),
                "author_association": comment.get('author_association', '')
            }
            structured_general_comments.append(comment_info)
        
        # Get unique reviewers
        unique_reviewers = list(set(
            [r['reviewer_username'] for r in structured_reviews] +
            [c['reviewer_username'] for c in structured_review_comments]
        ))
        
        # Count review states
        approval_count = len([r for r in structured_reviews if r['state'] == 'APPROVED'])
        changes_requested = len([r for r in structured_reviews if r['state'] == 'CHANGES_REQUESTED'])
        comment_only = len([r for r in structured_reviews if r['state'] == 'COMMENTED'])
        
        return {
            "pr_id": str(uuid.uuid4()),
            "repo_name": f"{pr['base']['repo']['owner']['login']}/{pr['base']['repo']['name']}",
            "pr_number": pr['number'],
            "title": pr['title'],
            "state": pr['state'],
            "author": {
                "username": pr['user']['login'],
                "id": pr['user']['id'],
                "profile_url": pr['user']['html_url']
            },
            "created_at": pr['created_at'],
            "updated_at": pr['updated_at'],
            "merged_at": pr.get('merged_at'),
            "merged_by": {
                "username": pr['merged_by']['login'] if pr.get('merged_by') else None,
                "id": pr['merged_by']['id'] if pr.get('merged_by') else None,
                "profile_url": pr['merged_by']['html_url'] if pr.get('merged_by') else None
            } if pr.get('merged_by') else None,
            "description": pr['body'] or "",
            "labels": [label['name'] for label in pr.get('labels', [])],
            "additions": pr.get('additions', 0),
            "deletions": pr.get('deletions', 0),
            "changed_files_count": pr.get('changed_files', 0),
            "is_draft": pr.get('draft', False),
            
            # Reviewer-focused data
            "reviews": structured_reviews,
            "review_comments": structured_review_comments,
            "general_comments": structured_general_comments,
            "reviewer_summary": {
                "total_reviews": len(structured_reviews),
                "total_review_comments": len(structured_review_comments),
                "total_general_comments": len(structured_general_comments),
                "unique_reviewers": unique_reviewers,
                "approval_count": approval_count,
                "changes_requested_count": changes_requested,
                "comment_only_count": comment_only
            }
        }
    
    def fetch_repository_reviewer_data(
        self,
        owner: str,
        repo: str,
        max_prs: Optional[int] = None
    ) -> Dict:
        """
        Fetch reviewer data for entire repository
        
        Args:
            owner: Repository owner
            repo: Repository name
            max_prs: Maximum PRs to fetch (uses config default if None)
        
        Returns:
            Complete repository reviewer data with metadata
        """
        if max_prs is None:
            max_prs = self.max_prs
        
        logger.info(f"🔍 Fetching reviewer data from {owner}/{repo} (max {max_prs} PRs)")
        
        all_reviewer_data = []
        page = 1
        prs_collected = 0
        
        while prs_collected < max_prs:
            per_page = min(30, max_prs - prs_collected)
            
            logger.info(f"📄 Fetching page {page} (PRs {prs_collected + 1}-{prs_collected + per_page})")
            
            prs = self.client.get_pull_requests(
                owner, repo,
                state='all',
                per_page=per_page,
                page=page,
                sort='updated',
                direction='desc'
            )
            
            if not prs:
                logger.info("✅ No more PRs available")
                break
            
            for pr in prs:
                pr_number = pr['number']
                logger.info(f"  📋 Processing PR #{pr_number}: {pr['title'][:60]}...")
                
                pr_data = self.fetch_pr_reviewer_data(owner, repo, pr_number)
                
                if pr_data and (pr_data['reviews'] or pr_data['review_comments']):
                    all_reviewer_data.append(pr_data)
                    reviewer_count = len(pr_data['reviewer_summary']['unique_reviewers'])
                    logger.info(
                        f"    ✅ Found {len(pr_data['reviews'])} reviews, "
                        f"{len(pr_data['review_comments'])} comments from {reviewer_count} reviewers"
                    )
                else:
                    logger.debug("    ⚠️ No reviewer activity found")
                
                prs_collected += 1
                if prs_collected >= max_prs:
                    break
            
            page += 1
        
        # Analyze reviewer patterns
        logger.info("📊 Analyzing reviewer patterns...")
        reviewer_profiles = self._analyze_reviewer_patterns(all_reviewer_data)
        
        # Generate metadata
        timestamp = get_timestamp()
        metadata = {
            'repository': f"{owner}/{repo}",
            'collection_date': timestamp,
            'total_prs_analyzed': len(all_reviewer_data),
            'total_reviewers_found': len(reviewer_profiles),
            'collection_parameters': {
                'max_prs_fetched': max_prs,
            }
        }
        
        logger.info(
            f"✅ Collection complete: {len(all_reviewer_data)} PRs, "
            f"{len(reviewer_profiles)} reviewers"
        )
        
        return {
            'metadata': metadata,
            'pr_reviewer_data': all_reviewer_data,
            'reviewer_profiles': reviewer_profiles
        }
    
    def _analyze_reviewer_patterns(self, reviewer_data: List[Dict]) -> Dict:
        """Analyze patterns and generate reviewer profiles"""
        
        reviewer_profiles = defaultdict(lambda: {
            'username': '',
            'profile_url': '',
            'avatar_url': '',
            'user_id': None,
            'total_prs_reviewed': 0,
            'total_formal_reviews': 0,
            'total_review_comments': 0,
            'total_general_comments': 0,
            'review_states': {
                'APPROVED': 0,
                'CHANGES_REQUESTED': 0,
                'COMMENTED': 0,
                'DISMISSED': 0
            },
            'author_associations': defaultdict(int),
            'prs_reviewed': [],
            'review_activity_by_month': defaultdict(int),
            'repositories_reviewed': set()
        })
        
        for pr_data in reviewer_data:
            repo_name = pr_data['repo_name']
            pr_number = pr_data['pr_number']
            
            # Process formal reviews
            for review in pr_data['reviews']:
                username = review['reviewer_username']
                profile = reviewer_profiles[username]
                
                # Basic info
                profile['username'] = username
                profile['profile_url'] = review['reviewer_profile_url']
                profile['avatar_url'] = review['reviewer_avatar_url']
                profile['user_id'] = review['reviewer_id']
                
                # Counts
                profile['total_formal_reviews'] += 1
                profile['review_states'][review['state']] += 1
                profile['author_associations'][review['author_association']] += 1
                
                if pr_number not in profile['prs_reviewed']:
                    profile['prs_reviewed'].append(pr_number)
                    profile['total_prs_reviewed'] += 1
                
                profile['repositories_reviewed'].add(repo_name)
                
                # Activity by month
                review_date = datetime.fromisoformat(review['submitted_at'].replace('Z', '+00:00'))
                month_key = review_date.strftime('%Y-%m')
                profile['review_activity_by_month'][month_key] += 1
            
            # Process review comments
            for comment in pr_data['review_comments']:
                username = comment['reviewer_username']
                profile = reviewer_profiles[username]
                
                profile['username'] = username
                profile['profile_url'] = comment['reviewer_profile_url']
                profile['user_id'] = comment['reviewer_id']
                profile['total_review_comments'] += 1
                
                if pr_number not in profile['prs_reviewed']:
                    profile['prs_reviewed'].append(pr_number)
                    profile['total_prs_reviewed'] += 1
                
                profile['repositories_reviewed'].add(repo_name)
        
        # Convert sets to lists for JSON serialization
        for profile in reviewer_profiles.values():
            profile['repositories_reviewed'] = list(profile['repositories_reviewed'])
            profile['author_associations'] = dict(profile['author_associations'])
            profile['review_activity_by_month'] = dict(profile['review_activity_by_month'])
        
        return dict(reviewer_profiles)
    
    def save_to_file(self, data: Dict, owner: str, repo: str, output_dir: str = "data/raw/reviewers"):
        """
        Save reviewer data to JSON file
        
        Args:
            data: Reviewer data dictionary
            owner: Repository owner
            repo: Repository name
            output_dir: Output directory
        
        Returns:
            Path to saved file
        """
        timestamp = get_timestamp()
        filename = f"{owner}_{repo}_reviewer_data_{timestamp}.json"
        filepath = f"{output_dir}/{filename}"
        
        save_json(filepath, data)
        logger.info(f"💾 Saved reviewer data to {filepath}")
        
        return filepath


# Example usage and testing
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("👥 Testing Reviewer Data Fetcher")
    print("=" * 60)
    
    # Initialize fetcher
    fetcher = ReviewerDataFetcher()
    
    # Fetch data for a small sample
    data = fetcher.fetch_repository_reviewer_data(
        owner='moment',
        repo='moment',
        max_prs=5  # Small sample for testing
    )
    
    print(f"\n✅ Fetched data:")
    print(f"   PRs: {data['metadata']['total_prs_analyzed']}")
    print(f"   Reviewers: {data['metadata']['total_reviewers_found']}")
    
    # Save to file
    filepath = fetcher.save_to_file(data, 'moment', 'moment', 'data/raw/reviewers')
    print(f"\n💾 Saved to: {filepath}")
    
    print("\n✅ Reviewer data fetcher working correctly!")