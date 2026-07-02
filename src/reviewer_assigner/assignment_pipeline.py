"""
Assignment Pipeline
Complete end-to-end workflow for PR reviewer assignment
"""

from typing import Dict, Optional
from pathlib import Path

from src.profile_generator.profile_storage import ProfileStorage
from src.reviewer_assigner.similarity_matcher import SimilarityMatcher
from src.reviewer_assigner.pr_analyzer import PRAnalyzer
from src.reviewer_assigner.reviewer_matcher import ReviewerMatcher
from src.reviewer_assigner.suggestion_formatter import SuggestionFormatter
from src.github_app.github_poster import GitHubPoster
from src.utils import get_logger, get_config, load_json

logger = get_logger(__name__)


class AssignmentPipeline:
    """Complete pipeline for reviewer assignment"""
    
    def __init__(
        self,
        github_token: Optional[str] = None,
        installation_id: Optional[int] = None,
        load_vector_store: bool = True
    ):
        """
        Initialize assignment pipeline
        
        Args:
            github_token: GitHub token (optional)
            installation_id: GitHub App installation ID (for app auth)
            load_vector_store: Whether to load existing vector store
        """
        self.config = get_config()
        self.installation_id = installation_id
        
        logger.info("🚀 Initializing Assignment Pipeline...")
        
        # Initialize components
        self.storage = ProfileStorage()
        self.pr_analyzer = PRAnalyzer()
        self.formatter = SuggestionFormatter()
        
        # Initialize similarity matcher
        self.similarity_matcher = SimilarityMatcher()
        
        # Try to load existing vector store
        if load_vector_store:
            vector_store_path = "reviewer_vectors.faiss"
            if self.similarity_matcher.load_vector_store(vector_store_path):
                logger.info("✅ Loaded existing vector store")
            else:
                logger.warning("⚠️ No vector store found - similarity matching will be limited")
        
        # Initialize reviewer matcher
        self.reviewer_matcher = ReviewerMatcher(
            profile_storage=self.storage,
            similarity_matcher=self.similarity_matcher
        )
        
        # Initialize GitHub poster (optional).
        # installation_id is passed through so App-installation auth is used
        # when available (multi-tenant posting); falls back to GITHUB_TOKEN.
        try:
            self.github_poster = GitHubPoster(github_token, installation_id=installation_id)
        except ValueError:
            logger.warning("⚠️ GitHub poster not initialized - posting disabled")
            self.github_poster = None
        
        logger.info("✅ Assignment Pipeline initialized")
    
    def process_pr(
        self,
        pr_data: Dict,
        post_to_github: bool = False,
        dry_run: bool = True,
        github_poster: Optional[GitHubPoster] = None
    ) -> Dict:
        """
        Complete workflow: analyze PR → match reviewers → format suggestions

        Args:
            pr_data: PR data dictionary (must include: pr_number, title, description,
                     author, repo_name, changed_files, additions, deletions, labels)
            post_to_github: Whether to post suggestions to GitHub
            dry_run: If True, simulates GitHub posting without actually posting
            github_poster: Optional per-request poster (e.g. built with the
                     webhook's installation_id). Falls back to the pipeline's
                     default poster. Passing it per request keeps a shared
                     singleton pipeline thread-safe across concurrent webhooks.

        Returns:
            {
                'pr_data': Dict,
                'pr_requirements': Dict,
                'recommendations': Dict,
                'formatted_comment': str,
                'posted_to_github': bool
            }
        """
        pr_number = pr_data.get('pr_number', 0)
        repo_name = pr_data.get('repo_name', 'Unknown')
        
        logger.info(f"🔄 Processing PR #{pr_number} from {repo_name}")
        
        result = {
            'pr_data': pr_data,
            'pr_requirements': None,
            'recommendations': None,
            'formatted_comment': None,
            'posted_to_github': False
        }
        
        # Step 1: Analyze PR
        logger.info("📊 Step 1/4: Analyzing PR requirements...")
        pr_requirements = self.pr_analyzer.analyze_pr(pr_data)
        
        if not pr_requirements:
            logger.error("❌ PR analysis failed")
            return result
        
        result['pr_requirements'] = pr_requirements
        logger.info(f"✅ Analysis complete: {pr_requirements['complexity_level']} complexity, "
                   f"{len(pr_requirements['technical_skills_needed'])} skills identified")
        
        # Step 2: Match reviewers
        logger.info("🎯 Step 2/4: Matching reviewers...")
        recommendations = self.reviewer_matcher.match_reviewers(
            pr_requirements=pr_requirements,
            pr_data=pr_data
        )
        
        result['recommendations'] = recommendations
        
        num_reviewers = len(recommendations.get('recommended_reviewers', []))
        confidence = recommendations.get('assignment_confidence', 'Unknown')
        logger.info(f"✅ Matched {num_reviewers} reviewers (confidence: {confidence})")
        
        # Step 3: Format suggestions
        logger.info("📝 Step 3/4: Formatting suggestions...")
        formatted_comment = self.formatter.format_as_markdown(
            recommendations=recommendations,
            pr_data=pr_data,
            pr_requirements=pr_requirements
        )
        
        result['formatted_comment'] = formatted_comment
        logger.info(f"✅ Formatted {len(formatted_comment)} characters of markdown")
        
        # Step 4: Post to GitHub (optional)
        poster = github_poster or self.github_poster
        if post_to_github and poster:
            logger.info("💬 Step 4/4: Posting to GitHub...")

            # Use update-or-create so that webhook retries / reopened events do
            # NOT spam the PR with duplicate comments. If a bot comment already
            # exists it is edited in place; otherwise a new one is created.
            success = poster.update_existing_comment(
                repo_full_name=repo_name,
                pr_number=pr_number,
                comment_body=formatted_comment,
                dry_run=dry_run
            )
            
            result['posted_to_github'] = success
            
            if success:
                if dry_run:
                    logger.info("✅ Dry run successful - would post to GitHub")
                else:
                    logger.info("✅ Posted to GitHub successfully")
            else:
                logger.error("❌ Failed to post to GitHub")
        else:
            logger.info("ℹ️ Step 4/4: Skipping GitHub posting")
        
        logger.info(f"🎉 Pipeline complete for PR #{pr_number}")
        return result
    
    def process_pr_from_github(
        self,
        repo_full_name: str,
        pr_number: int,
        post_to_github: bool = False,
        dry_run: bool = True
    ) -> Dict:
        """
        Fetch PR from GitHub and process it
        
        Args:
            repo_full_name: Repository name (e.g., 'moment/moment')
            pr_number: PR number
            post_to_github: Whether to post suggestions back
            dry_run: If True, simulates posting
        
        Returns:
            Processing result dictionary
        """
        if not self.github_poster:
            logger.error("❌ GitHub poster not initialized")
            return {}
        
        logger.info(f"📥 Fetching PR #{pr_number} from {repo_full_name}...")
        
        # Fetch PR data
        pr_data = self.github_poster.get_pr_data(repo_full_name, pr_number)
        
        if not pr_data:
            logger.error("❌ Failed to fetch PR data")
            return {}
        
        # Process PR
        return self.process_pr(
            pr_data=pr_data,
            post_to_github=post_to_github,
            dry_run=dry_run
        )
    
    def create_vector_store_from_data(
        self,
        reviewer_data_file: str,
        save_to_disk: bool = True
    ) -> bool:
        """
        Create vector embeddings from reviewer data file
        
        Args:
            reviewer_data_file: Path to reviewer data JSON file
            save_to_disk: Whether to save vector store to disk
        
        Returns:
            Success boolean
        """
        logger.info(f"📦 Creating vector store from {reviewer_data_file}...")
        
        # Load reviewer data
        data = load_json(reviewer_data_file)
        
        if not data:
            logger.error("❌ Failed to load reviewer data")
            return False
        
        pr_data = data.get('pr_reviewer_data', [])
        
        if not pr_data:
            logger.error("❌ No PR data found in file")
            return False
        
        # Create embeddings
        success = self.similarity_matcher.create_embeddings_from_reviewer_data(pr_data)
        
        if not success:
            logger.error("❌ Failed to create embeddings")
            return False
        
        # Save to disk
        if save_to_disk:
            self.similarity_matcher.save_vector_store("reviewer_vectors.faiss")
        
        logger.info("✅ Vector store created successfully")
        return True


# Example usage and testing
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("🚀 Testing Assignment Pipeline")
    print("=" * 80)
    
    # Sample PR data (in real use, this comes from GitHub webhook)
    sample_pr = {
        'pr_number': 1234,
        'title': 'Fix Express.js routing bug in API endpoints',
        'description': '''
This PR fixes a critical bug in the Express.js routing middleware that was causing
incorrect route matching for nested API endpoints.

Changes:
- Updated route matching logic in src/routes/api.js
- Added unit tests using Jest
- Fixed middleware chain ordering
- Updated documentation

The issue was caused by incorrect regex patterns in the path-to-regexp matcher.
        ''',
        'author': {'username': 'developer1'},
        'repo_name': 'moment/moment',
        'changed_files': [
            'src/routes/api.js',
            'test/routes/api.test.js',
            'docs/api-routing.md',
            'package.json'
        ],
        'additions': 85,
        'deletions': 42,
        'labels': ['bug', 'backend', 'high-priority']
    }
    
    try:
        # Initialize pipeline
        print("\n🔧 Initializing pipeline...")
        pipeline = AssignmentPipeline(load_vector_store=False)
        print("✅ Pipeline initialized")
        
        # Process PR
        print("\n🔄 Processing sample PR...")
        print("-" * 80)
        
        result = pipeline.process_pr(
            pr_data=sample_pr,
            post_to_github=False,  # Don't post for this test
            dry_run=True
        )
        
        # Display results
        print("\n" + "=" * 80)
        print("📊 PIPELINE RESULTS")
        print("=" * 80)
        
        if result['pr_requirements']:
            print("\n✅ PR Requirements:")
            print(f"   Complexity: {result['pr_requirements']['complexity_level']}")
            print(f"   Skills: {', '.join(result['pr_requirements']['technical_skills_needed'][:3])}")
        
        if result['recommendations']:
            recs = result['recommendations']['recommended_reviewers']
            print(f"\n✅ Matched {len(recs)} Reviewers:")
            for i, rec in enumerate(recs, 1):
                print(f"   {i}. {rec['reviewer_name']} ({rec['match_score']:.1%})")
        
        if result['formatted_comment']:
            print(f"\n✅ Formatted Comment ({len(result['formatted_comment'])} chars)")
            print("\n" + "-" * 80)
            print("Preview (first 500 chars):")
            print("-" * 80)
            print(result['formatted_comment'][:500] + "...")
        
        print("\n" + "=" * 80)
        print("✅ Assignment Pipeline working correctly!")
        print("=" * 80)
        
        # Show how to use with real GitHub PR
        print("\n📚 To process a real GitHub PR:")
        print("-" * 80)
        print("pipeline = AssignmentPipeline()")
        print("result = pipeline.process_pr_from_github(")
        print("    repo_full_name='moment/moment',")
        print("    pr_number=1234,")
        print("    post_to_github=True,")
        print("    dry_run=False  # Set to False to actually post")
        print(")")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()