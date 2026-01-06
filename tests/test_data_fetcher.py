"""
Test data fetcher modules
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

load_dotenv()

from src.data_fetcher import GitHubClient, ReviewerDataFetcher


def test_github_client():
    """Test GitHub API client"""
    print("\n🔌 Testing GitHub Client...")
    
    client = GitHubClient()
    
    # Test repository access
    repo = client.get_repository('moment', 'moment')
    assert repo is not None, "Failed to fetch repository"
    print(f"  ✓ Repository: {repo['full_name']}")
    
    # Test PR fetching
    prs = client.get_pull_requests('moment', 'moment', per_page=2)
    assert prs is not None and len(prs) > 0, "Failed to fetch PRs"
    print(f"  ✓ Fetched {len(prs)} PRs")
    
    print("✅ GitHub client tests passed!")


def test_reviewer_data_fetcher():
    """Test reviewer data fetcher"""
    print("\n👥 Testing Reviewer Data Fetcher...")

    fetcher = ReviewerDataFetcher()

    # Fetch small sample
    data = fetcher.fetch_repository_reviewer_data(
        owner='moment',
        repo='moment',
        max_prs=3  # Very small sample for testing
    )

    assert 'metadata' in data, "Missing metadata"
    assert 'pr_reviewer_data' in data, "Missing PR data"
    assert 'reviewer_profiles' in data, "Missing reviewer profiles"

    print(f"  ✓ Fetched {data['metadata']['total_prs_analyzed']} PRs")
    print(f"  ✓ Found {data['metadata']['total_reviewers_found']} reviewers")

    print("✅ Reviewer data fetcher tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("TESTING DATA FETCHER")
    print("=" * 60)
    try:
        test_github_client()
        test_reviewer_data_fetcher()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()