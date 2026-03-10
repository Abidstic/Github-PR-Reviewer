#!/usr/bin/env python3
"""
GitHub Reviewer AI - Main Application Entry Point

This is the unified entry point for the GitHub Reviewer AI system.
It provides different modes of operation:
- setup: Initial setup (fetch data, generate profiles, create vector store)
- webhook: Run webhook server for GitHub App
- update-profiles: Update existing reviewer profiles
"""

import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

from src.utils import get_logger, get_config

# Load environment variables
load_dotenv()

logger = get_logger(__name__)


def setup_mode(repo: str, max_prs: int = None, installation_id: int = None):
    """
    Initial setup: Fetch data, generate profiles, create vector store
    
    Args:
        repo: Repository in format 'owner/repo'
        max_prs: Maximum number of PRs to fetch (uses config default if None)
        installation_id: GitHub App installation ID (uses GITHUB_TOKEN if not provided)
    """
    from src.data_fetcher.reviewer_data_fetcher import ReviewerDataFetcher
    from src.profile_generator.reviewer_profile_builder import ReviewerProfileBuilder
    from src.profile_generator.profile_storage import ProfileStorage
    from src.reviewer_assigner.assignment_pipeline import AssignmentPipeline
    from src.data_fetcher.github_client import GitHubClient
    
    logger.info("=" * 80)
    logger.info("🚀 GITHUB REVIEWER AI - SETUP MODE")
    logger.info("=" * 80)
    
    # Parse repository
    try:
        owner, repo_name = repo.split('/')
    except ValueError:
        logger.error("❌ Invalid repository format. Use 'owner/repo'")
        return False
    
    logger.info(f"📦 Repository: {owner}/{repo_name}")
    logger.info(f"📊 Max PRs: {max_prs or 'config default'}")
    logger.info(f"🔑 Auth: {'App installation ' + str(installation_id) if installation_id else 'GITHUB_TOKEN'}")
    
    # Step 1: Fetch reviewer data
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: Fetching Reviewer Data from GitHub")
    logger.info("=" * 80)
    
    try:
        profile_storage = ProfileStorage()
        # Use installation_id if provided, otherwise fall back to GITHUB_TOKEN
        github_client = GitHubClient(installation_id=installation_id)
        fetcher = ReviewerDataFetcher(github_client=github_client)
        
        # Pass storage to handle PR-level checkpointing
        data = fetcher.fetch_repository_reviewer_data(
            owner=owner,
            repo=repo_name,
            max_prs_to_fetch=max_prs,
            storage=profile_storage
        )
        
        # Save raw data for this run
        data_file = fetcher.save_to_file(data, owner, repo_name)
        logger.info(f"✅ Data saved to: {data_file}")
        
    except Exception as e:
        logger.error(f"❌ Failed to fetch data: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    
    # Check if we actually got any new data
    total_new_prs = data.get('metadata', {}).get('total_prs_analyzed', 0)
    if total_new_prs == 0:
        logger.info("✨ No new PRs to process. All profiles are up to date!")
        return True

    # Step 2: Generate/Update reviewer profiles
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Generating/Updating Reviewer Profiles")
    logger.info("=" * 80)
    
    try:
        profile_builder = ReviewerProfileBuilder()
        
        reviewer_stats = data.get('reviewer_stats', {})
        logger.info(f"📊 Found {len(reviewer_stats)} reviewers with new activity")
        
        profiles_updated = 0
        
        for reviewer_name, new_stats in reviewer_stats.items():
            logger.info(f"🔄 Processing: {reviewer_name}")
            
            # Check for existing profile
            existing_profile = profile_storage.get_profile(reviewer_name)
            if existing_profile:
                logger.info(f"  ℹ️ Updating existing profile for {reviewer_name}")
            
            # 1. Build the profile object (calls LLM)
            profile_data = profile_builder.build_reviewer_profile(
                reviewer_name=reviewer_name,
                reviewer_stats=new_stats
            )
            
            if profile_data:
                # 2. Save to JSON and Database
                json_path, success = profile_storage.save_profile(profile_data)
                
                if success:
                    profiles_updated += 1
                    logger.info(f"✅ Profile updated and saved: {reviewer_name}")
                else:
                    logger.warning(f"⚠️ Failed to save profile to database: {reviewer_name}")
            else:
                logger.warning(f"⚠️ Could not generate profile for {reviewer_name} (check logs or min_reviews)")
        
        logger.info(f"\n✅ Total profiles updated: {profiles_updated}")
        
    except Exception as e:
        logger.error(f"❌ Failed to generate reviewer profiles: {e}")
        return False
    
    # Step 2.5: Generate/Update developer profiles
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2.5: Generating/Updating Developer Profiles")
    logger.info("=" * 80)
    
    try:
        from src.profile_generator.developer_profile_builder import DeveloperProfileBuilder
        
        dev_profile_builder = DeveloperProfileBuilder()
        
        developer_stats = data.get('developer_stats', {})
        logger.info(f"🔨 Found {len(developer_stats)} developers with new activity")
        
        dev_profiles_updated = 0
        
        for developer_name, stats in developer_stats.items():
            logger.info(f"🔄 Processing developer: {developer_name}")
            
            try:
                # Build and save profile
                profile_path = dev_profile_builder.build_and_save_profile(
                    developer_name=developer_name,
                    developer_stats=stats
                )
                
                if profile_path:
                    dev_profiles_updated += 1
                    logger.info(f"✅ Developer profile updated: {developer_name}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to update profile for {developer_name}: {e}")
        
        logger.info(f"\n✅ Total developer profiles updated: {dev_profiles_updated}")
        
    except Exception as e:
        logger.error(f"❌ Failed to generate developer profiles: {e}")
        # Don't fail the whole setup if developer profiles fail
        logger.warning("⚠️ Continuing without developer profiles")
    
    
    # Step 3: Create vector store
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Creating Vector Store for Similarity Matching")
    logger.info("=" * 80)
    
    try:
        pipeline = AssignmentPipeline(load_vector_store=False)
        
        # Create vector store from the data we just fetched
        success = pipeline.create_vector_store_from_data(
            reviewer_data_file=data_file,
            save_to_disk=True
        )
        
        if success:
            logger.info("✅ Vector store created successfully")
        else:
            logger.warning("⚠️ Vector store creation had issues")
        
    except Exception as e:
        logger.error(f"❌ Failed to create vector store: {e}")
        return False
    
    # Setup complete
    logger.info("\n" + "=" * 80)
    logger.info("✅ SETUP COMPLETE!")
    logger.info("=" * 80)
    logger.info("\nNext steps:")
    logger.info("1. Start webhook server: python app.py --mode webhook")
    logger.info("2. Configure GitHub App webhook to point to your server")
    logger.info("3. Install the app on your repository")
    
    return True


def webhook_mode(host: str = '0.0.0.0', port: int = 5000, debug: bool = False):
    """
    Run webhook server for GitHub App
    
    Args:
        host: Host to bind to
        port: Port to listen on
        debug: Enable debug mode
    """
    from src.github_app.webhook_server import run_server
    
    logger.info("=" * 80)
    logger.info("🌐 GITHUB REVIEWER AI - WEBHOOK MODE")
    logger.info("=" * 80)
    logger.info(f"\n🚀 Starting webhook server on {host}:{port}")
    logger.info(f"📡 Webhook endpoint: http://{host}:{port}/webhook")
    logger.info(f"💚 Health check: http://{host}:{port}/health")
    logger.info("\nPress Ctrl+C to stop")
    logger.info("=" * 80 + "\n")
    
    # Run the server
    run_server(host=host, port=port, debug=debug)


def update_profiles_mode(repo: str):
    """
    Update existing reviewer profiles with new data
    
    Args:
        repo: Repository in format 'owner/repo'
    """
    from src.data_fetcher.reviewer_data_fetcher import ReviewerDataFetcher
    from src.profile_generator.reviewer_profile_builder import ReviewerProfileBuilder
    from src.profile_generator.profile_storage import ProfileStorage
    
    logger.info("=" * 80)
    logger.info("🔄 GITHUB REVIEWER AI - UPDATE PROFILES MODE")
    logger.info("=" * 80)
    
    try:
        owner, repo_name = repo.split('/')
    except ValueError:
        logger.error("❌ Invalid repository format. Use 'owner/repo'")
        return False
    
    logger.info(f"📦 Repository: {owner}/{repo_name}")
    
    # Fetch latest data
    logger.info("\n🔄 Fetching latest PR data...")
    try:
        fetcher = ReviewerDataFetcher()
        data = fetcher.fetch_repository_reviewer_data(
            owner=owner,
            repo=repo_name,
            max_prs_to_fetch=50,  # Only fetch recent PRs for updates
            storage=profile_storage
        )
        
        # Update profiles
        profile_builder = ReviewerProfileBuilder()
        profile_storage = ProfileStorage()
        
        reviewer_stats = data.get('reviewer_stats', {})
        updated = 0
        
        for reviewer_name, stats in reviewer_stats.items():
            logger.info(f"🔄 Updating: {reviewer_name}")
            
            profile_data = profile_builder.build_reviewer_profile(
                reviewer_name=reviewer_name,
                reviewer_stats=stats
            )
            
            if profile_data:
                profile_storage.save_profile(profile_data)
                updated += 1
        
        logger.info(f"\n✅ Updated {updated} profiles")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to update profiles: {e}")
        return False


def main():
    """Main entry point with CLI argument parsing"""
    
    parser = argparse.ArgumentParser(
        description='GitHub Reviewer AI - Intelligent PR Reviewer Assignment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initial setup for a repository
  python app.py --mode setup --repo moment/moment
  
  # Run webhook server
  python app.py --mode webhook --port 5000
  
  # Update reviewer profiles
  python app.py --mode update-profiles --repo moment/moment
        """
    )
    
    parser.add_argument(
        '--mode',
        type=str,
        required=True,
        choices=['setup', 'webhook', 'update-profiles'],
        help='Operation mode'
    )
    
    parser.add_argument(
        '--repo',
        type=str,
        help='Repository in format owner/repo (required for setup and update-profiles)'
    )
    
    parser.add_argument(
        '--max-prs',
        type=int,
        help='Maximum number of PRs to fetch (for setup mode)'
    )
    
    parser.add_argument(
        '--host',
        type=str,
        default=os.getenv('WEBHOOK_HOST', '0.0.0.0'),
        help='Host to bind webhook server to (default: 0.0.0.0)'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=int(os.getenv('PORT', os.getenv('WEBHOOK_PORT', '5000'))),
        help='Port for webhook server (default: 5000, Railway uses PORT env var)'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )
    
    args = parser.parse_args()
    
    # Validate arguments based on mode
    if args.mode in ['setup', 'update-profiles'] and not args.repo:
        parser.error(f"--repo is required for {args.mode} mode")
    
    # Execute based on mode
    try:
        if args.mode == 'setup':
            success = setup_mode(repo=args.repo, max_prs=args.max_prs)
            sys.exit(0 if success else 1)
            
        elif args.mode == 'webhook':
            webhook_mode(host=args.host, port=args.port, debug=args.debug)
            
        elif args.mode == 'update-profiles':
            success = update_profiles_mode(repo=args.repo)
            sys.exit(0 if success else 1)
            
    except KeyboardInterrupt:
        logger.info("\n\n👋 Shutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    # Print banner
    print("\n" + "=" * 80)
    print("🤖 GITHUB REVIEWER AI".center(80))
    print("AI-Powered Code Reviewer Assignment System".center(80))
    print("=" * 80 + "\n")
    
    main()
