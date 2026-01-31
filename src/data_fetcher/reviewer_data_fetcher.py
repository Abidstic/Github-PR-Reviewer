"""
Reviewer Data Fetcher
Fetches PR review data from GitHub repositories
"""

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

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
        self.max_prs = self.config.get('github.max_prs_to_fetch')
        
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
        max_prs_to_fetch: Optional[int] = None,
        storage: Any = None
    ) -> Dict:
        """
        Fetch reviewer data for entire repository
        
        Args:
            owner: Repository owner
            repo: Repository name
            max_prs_to_fetch: Maximum PRs to fetch (uses config default if None)
            storage: Optional ProfileStorage to check for already processed PRs
        
        Returns:
            Complete repository reviewer data with metadata
        """
        max_prs = max_prs_to_fetch 
        repo_full_name = f"{owner}/{repo}"
        
        if max_prs is None:
            logger.info(f"📊 Fetching ALL PRs for {repo_full_name} (unlimited)")
            max_prs = float('inf')  
        else:
            logger.info(f"📊 Fetching max {max_prs} PRs for {repo_full_name}")
        
        all_reviewer_data = []
        page = 1
        prs_collected = 0
        skipped_checkpoint = 0
        
        while max_prs == float('inf') or prs_collected < max_prs:
            per_page = min(30, max_prs - prs_collected) if max_prs != float('inf') else 30
            
            logger.info(f"📄 Fetching page {page} for {repo_full_name}")
            
            prs = self.client.get_pull_requests(
                owner, repo,
                state='all',
                per_page=per_page,
                page=page,
                sort='created', # Use created to make it easier to stop when we hit old PRs
                direction='desc'
            )
            
            if not prs:
                logger.info("✅ No more PRs available")
                break
            
            for pr in prs:
                pr_number = pr['number']
                
                # Check checkpoint
                if storage and hasattr(storage, 'is_pr_processed'):
                    if storage.is_pr_processed(repo_full_name, pr_number):
                        logger.info(f"  ⏭️ Skipping PR #{pr_number} (already processed in checkpoint)")
                        skipped_checkpoint += 1
                        prs_collected += 1
                        
                        # If we are fetching "all" and hit a processed PR, we might want to stop
                        # but some newer PRs might be below? Usually desc 'created' is safe to stop.
                        # However, to be safe, we'll continue for now unless we hit a long streak.
                        if skipped_checkpoint > 50 and max_prs == float('inf'):
                            logger.info("🛑 Hit a streak of 50 processed PRs. Assuming we're up to date.")
                            max_prs = 0 # Break outer loop too
                            break
                        continue
                
                logger.info(f"  📋 Processing PR #{pr_number}: {pr['title'][:60]}...")
                
                pr_data = self.fetch_pr_reviewer_data(owner, repo, pr_number)
                
                if pr_data:
                    all_reviewer_data.append(pr_data)
                    reviewer_count = len(pr_data['reviewer_summary']['unique_reviewers'])
                    logger.info(
                        f"    ✅ Found {len(pr_data['reviews'])} reviews from {reviewer_count} reviewers"
                    )
                    
                    # Mark as processed if we have storage
                    if storage and hasattr(storage, 'mark_pr_processed'):
                        storage.mark_pr_processed(repo_full_name, pr_number)
                else:
                    logger.debug("    ⚠️ No data found")
                
                prs_collected += 1
                if prs_collected >= max_prs:
                    break
            
            if max_prs == 0: break
            page += 1
        
        # Analyze reviewer patterns
        logger.info("📊 Analyzing reviewer patterns...")
        reviewer_profiles = self._analyze_reviewer_patterns(all_reviewer_data)
        
        # Analyze developer patterns
        logger.info("🔨 Analyzing developer patterns...")
        developer_profiles = self._analyze_developer_patterns(all_reviewer_data)
        
        # Generate metadata
        timestamp = get_timestamp()
        metadata = {
            'repository': f"{owner}/{repo}",
            'collection_date': timestamp,
            'total_prs_analyzed': len(all_reviewer_data),
            'total_reviewers_found': len(reviewer_profiles),
            'total_developers_found': len(developer_profiles),
            'collection_parameters': {
                'max_prs_fetched': max_prs,
            }
        }
        
        logger.info(
            f"✅ Collection complete: {len(all_reviewer_data)} PRs, "
            f"{len(reviewer_profiles)} reviewers, {len(developer_profiles)} developers"
        )
        
        return {
            'metadata': metadata,
            'pr_reviewer_data': all_reviewer_data,
            'reviewer_stats': reviewer_profiles,
            'developer_stats': developer_profiles
        }
    
    def _analyze_reviewer_patterns(self, reviewer_data: List[Dict]) -> Dict:
        """Analyze patterns and generate reviewer profiles"""
        
        reviewer_profiles = defaultdict(lambda: {
            'username': '',
            'profile_url': '',
            'avatar_url': '',
            'user_id': None,
            'total_prs_reviewed': 0,
            'total_reviews': 0,
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
            'review_details': [],
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
                profile['total_reviews'] += 1
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

                # Review Details for LLM analysis
                profile['review_details'].append({
                    'title': pr_data.get('title'),
                    'repo': repo_name,
                    'labels': pr_data.get('labels', []),
                    'review_state': review['state'],
                    'additions': pr_data.get('additions', 0),
                    'deletions': pr_data.get('deletions', 0),
                    'changed_files_count': pr_data.get('changed_files_count', 0),
                    'description': pr_data.get('description', ''),
                    'review_body': review.get('body', ''),
                    'submitted_at': review['submitted_at']
                })
            
            # Process review comments
            for comment in pr_data['review_comments']:
                username = comment['reviewer_username']
                profile = reviewer_profiles[username]
                
                profile['username'] = username
                profile['profile_url'] = comment['reviewer_profile_url']
                profile['user_id'] = comment['reviewer_id']
                profile['total_review_comments'] += 1
                profile['total_reviews'] += 1
                
                if pr_number not in profile['prs_reviewed']:
                    profile['prs_reviewed'].append(pr_number)
                    profile['total_prs_reviewed'] += 1
                
                profile['repositories_reviewed'].add(repo_name)
                
                # Add comment details for LLM
                profile['review_details'].append({
                    'title': pr_data.get('title'),
                    'repo': repo_name,
                    'labels': pr_data.get('labels', []),
                    'review_state': 'COMMENTED',
                    'additions': pr_data.get('additions', 0),
                    'deletions': pr_data.get('deletions', 0),
                    'changed_files_count': pr_data.get('changed_files_count', 0),
                    'description': pr_data.get('description', ''),
                    'review_body': comment.get('body', ''),
                    'submitted_at': comment.get('created_at', '')
                })
        
        # Convert sets to lists for JSON serialization
        for profile in reviewer_profiles.values():
            profile['repositories_reviewed'] = list(profile['repositories_reviewed'])
            profile['author_associations'] = dict(profile['author_associations'])
            profile['review_activity_by_month'] = dict(profile['review_activity_by_month'])
        
        return dict(reviewer_profiles)
    
    def _analyze_developer_patterns(self, pr_data_list: List[Dict]) -> Dict:
        """Analyze patterns and generate developer profiles"""
        
        developer_profiles = defaultdict(lambda: {
            'username': '',
            'profile_url': '',
            'avatar_url': '',
            'user_id': None,
            'total_prs_created': 0,
            'total_merged_prs': 0,
            'total_additions': 0,
            'total_deletions': 0,
            'total_files_changed': 0,
            'labels_used': defaultdict(int),
            'pr_titles': [],
            'repositories': set(),
            'activity_by_month': defaultdict(int),
            'pr_states': defaultdict(int)
        })
        
        for pr_data in pr_data_list:
            author = pr_data['author']
            username = author['username']
            profile = developer_profiles[username]
            
            # Basic info
            profile['username'] = username
            profile['profile_url'] = author['profile_url']
            profile['user_id'] = author['id']
            
            # PR counts
            profile['total_prs_created'] += 1
            if pr_data.get('merged_at'):
                profile['total_merged_prs'] += 1
            
            # Code changes
            profile['total_additions'] += pr_data.get('additions', 0)
            profile['total_deletions'] += pr_data.get('deletions', 0)
            profile['total_files_changed'] += pr_data.get('changed_files_count', 0)
            
            # Labels
            for label in pr_data.get('labels', []):
                profile['labels_used'][label] += 1
            
            # PR titles (for pattern analysis)
            if pr_data.get('title'):
                profile['pr_titles'].append(pr_data['title'])
            
            # Repositories
            profile['repositories'].add(pr_data['repo_name'])
            
            # Activity by month
            created_at = pr_data.get('created_at')
            if created_at:
                pr_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                month_key = pr_date.strftime('%Y-%m')
                profile['activity_by_month'][month_key] += 1
            
            # PR states
            profile['pr_states'][pr_data.get('state', 'unknown')] += 1
        
        # Calculate averages and convert sets to lists
        for profile in developer_profiles.values():
            total_prs = profile['total_prs_created']
            if total_prs > 0:
                profile['avg_additions'] = profile['total_additions'] / total_prs
                profile['avg_deletions'] = profile['total_deletions'] / total_prs
                profile['avg_files_changed'] = profile['total_files_changed'] / total_prs
            else:
                profile['avg_additions'] = 0
                profile['avg_deletions'] = 0
                profile['avg_files_changed'] = 0
            
            # Convert to serializable types
            profile['repositories'] = list(profile['repositories'])
            profile['labels_used'] = dict(profile['labels_used'])
            profile['activity_by_month'] = dict(profile['activity_by_month'])
            profile['pr_states'] = dict(profile['pr_states'])
        
        return dict(developer_profiles)
    
    
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
        max_prs_to_fetch=10
    )
    
    print(f"\n✅ Fetched data:")
    print(f"   PRs: {data['metadata']['total_prs_analyzed']}")
    print(f"   Reviewers: {data['metadata']['total_reviewers_found']}")
    
    # Save to file
    filepath = fetcher.save_to_file(data, 'moment', 'moment', 'data/raw/reviewers')
    print(f"\n💾 Saved to: {filepath}")
    
    print("\n✅ Reviewer data fetcher working correctly!")