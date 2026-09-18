#!/usr/bin/env python3
"""
GitHub Reviewer AI - Main Application Entry Point

Modes:
- setup: Populate rolling window, generate unified profiles, build FAISS
- webhook: Run webhook server for GitHub App
"""

import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

from src.utils import get_logger, get_config

load_dotenv()

logger = get_logger(__name__)


def _get_installation_id_for_repo(owner: str, repo_name: str) -> int:
    """Look up the GitHub App installation ID for a given repo."""
    import time
    import jwt as pyjwt
    import urllib.request
    import json

    app_id = os.getenv('GITHUB_APP_ID')
    private_key = os.getenv('GITHUB_PRIVATE_KEY')
    if not private_key:
        key_path = os.getenv('GITHUB_PRIVATE_KEY_PATH')
        if key_path:
            with open(key_path, 'r') as f:
                private_key = f.read()

    if not app_id or not private_key:
        raise ValueError("GITHUB_APP_ID and GITHUB_PRIVATE_KEY must be set")

    now = int(time.time())
    payload = {'iat': now - 60, 'exp': now + (10 * 60), 'iss': app_id}
    app_jwt = pyjwt.encode(payload, private_key, algorithm='RS256')

    url = f"https://api.github.com/repos/{owner}/{repo_name}/installation"
    req = urllib.request.Request(url)
    req.add_header('Authorization', f'Bearer {app_jwt}')
    req.add_header('Accept', 'application/vnd.github+json')

    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode('utf-8'))
        return data['id']


def _fetch_merged_prs(github_client, owner: str, repo: str,
                      max_prs: int, label_repo: str) -> list:
    """
    Fetch merged PRs with reviews and review comments from GitHub API.
    Returns a list of dicts suitable for WindowManager.populate_window(),
    ordered oldest-first.
    """
    from src.github_app.webhook_handler import WebhookHandler

    collected = []
    page = 1
    per_page = 100

    while len(collected) < max_prs:
        prs = github_client.get_pull_requests(
            owner, repo, state='closed',
            per_page=per_page, page=page,
            sort='created', direction='desc'
        )
        if not prs:
            break

        for pr_raw in prs:
            if len(collected) >= max_prs:
                break
            if not pr_raw.get('merged_at'):
                continue

            pr_number = pr_raw['number']
            logger.info(f"  Fetching PR #{pr_number} data...")

            files = github_client.get_pr_files(owner, repo, pr_number) or []
            changed_files = [f.get('filename') for f in files]
            raw_reviews = github_client.get_pr_reviews(
                owner, repo, pr_number
            ) or []
            raw_comments = github_client.get_pr_review_comments(
                owner, repo, pr_number
            ) or []

            pr_data = WebhookHandler._extract_merged_pr_data(
                pr_raw, label_repo, changed_files
            )
            reviews = WebhookHandler._transform_reviews(raw_reviews)
            review_comments = WebhookHandler._transform_review_comments(
                raw_comments
            )

            collected.append({
                'pr_data': pr_data,
                'reviews': reviews,
                'review_comments': review_comments,
            })

        if len(prs) < per_page:
            break
        page += 1

    # populate_window expects oldest-first
    collected.reverse()
    logger.info(f"Fetched {len(collected)} merged PRs")
    return collected


def setup_mode(repo: str, max_prs: int = None,
               installation_id: int = None):
    """
    Initial setup: fetch merged PRs into rolling window, generate
    unified profiles via LLM, build FAISS index.
    """
    from src.data_fetcher.github_client import GitHubClient
    from src.storage.window_manager import WindowManager
    from src.reviewer_assigner.assignment_pipeline import AssignmentPipeline

    config = get_config()

    logger.info("=" * 80)
    logger.info("GITHUB REVIEWER AI - SETUP MODE")
    logger.info("=" * 80)

    try:
        owner, repo_name = repo.split('/')
    except ValueError:
        logger.error("Invalid repository format. Use 'owner/repo'")
        return False

    logger.info(f"Repository: {owner}/{repo_name}")

    if not installation_id:
        try:
            installation_id = _get_installation_id_for_repo(owner, repo_name)
            logger.info(f"Auto-resolved installation_id: {installation_id}")
        except Exception as e:
            logger.warning(
                f"Could not auto-resolve installation_id ({e}), "
                "falling back to GITHUB_TOKEN"
            )

    # Fork detection
    source_owner, source_repo = owner, repo_name
    label_repo = f"{owner}/{repo_name}"
    is_fork = False
    try:
        probe_client = GitHubClient(installation_id=installation_id)
        repo_info = probe_client.get_repository(owner, repo_name)
        if repo_info is None:
            logger.warning("Repo info fetch failed with installation auth "
                           "- retrying with GITHUB_TOKEN")
            repo_info = GitHubClient().get_repository(owner, repo_name)

        if repo_info and repo_info.get('fork') and repo_info.get('parent'):
            is_fork = True
            parent_full_name = repo_info['parent']['full_name']
            source_owner, source_repo = parent_full_name.split('/')
            if max_prs is None:
                max_prs = config.get('github.fork_setup_max_prs', 300)
            logger.info(f"FORK DETECTED — data source: {parent_full_name}")
    except Exception as e:
        logger.warning(f"Fork detection failed ({e})")

    if max_prs is None:
        max_prs = 500

    # Step 1: Fetch merged PRs
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: Fetching merged PRs from GitHub")
    logger.info("=" * 80)

    if is_fork:
        github_client = GitHubClient()
    else:
        github_client = GitHubClient(installation_id=installation_id)

    pr_list = _fetch_merged_prs(
        github_client, source_owner, source_repo, max_prs, label_repo
    )

    if not pr_list:
        logger.warning("No merged PRs found")
        return True

    # Step 2: Populate rolling window
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: Populating rolling window")
    logger.info("=" * 80)

    wm = WindowManager()
    parent_repo = f"{source_owner}/{source_repo}" if is_fork else None
    wm.init_repo(label_repo, is_fork=is_fork, parent_repo=parent_repo)
    added = wm.populate_window(label_repo, pr_list)
    logger.info(f"Added {added} PRs to window")

    # Step 3: Generate unified profiles via LLM
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: Generating unified profiles (LLM)")
    logger.info("=" * 80)

    try:
        from src.profile_generator.unified_profile_builder import (
            UnifiedProfileBuilder,
        )
        builder = UnifiedProfileBuilder(window_manager=wm)
        results = builder.generate_all_profiles(label_repo)
        succeeded = sum(1 for v in results.values() if v)
        logger.info(f"Profiles generated: {succeeded}/{len(results)}")
    except Exception as e:
        logger.error(f"Profile generation failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

    # Step 4: Build FAISS index
    logger.info("\n" + "=" * 80)
    logger.info("STEP 4: Building FAISS index")
    logger.info("=" * 80)

    try:
        pipeline = AssignmentPipeline(
            window_manager=wm, load_vector_store=False
        )
        pipeline.build_faiss_from_window(label_repo)
    except Exception as e:
        logger.error(f"FAISS build failed: {e}")

    logger.info("\n" + "=" * 80)
    logger.info("SETUP COMPLETE")
    logger.info("=" * 80)
    return True


def webhook_mode(host: str = '0.0.0.0', port: int = 5000,
                 debug: bool = False):
    """Run webhook server for GitHub App."""
    from src.github_app.webhook_server import run_server

    logger.info("=" * 80)
    logger.info("GITHUB REVIEWER AI - WEBHOOK MODE")
    logger.info("=" * 80)
    logger.info(f"Starting webhook server on {host}:{port}")
    run_server(host=host, port=port, debug=debug)


def main():
    parser = argparse.ArgumentParser(
        description='GitHub Reviewer AI - Intelligent PR Reviewer Assignment',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python app.py --mode setup --repo moment/moment
  python app.py --mode webhook --port 5000
        """
    )

    parser.add_argument(
        '--mode', type=str, required=True,
        choices=['setup', 'webhook'],
        help='Operation mode'
    )
    parser.add_argument(
        '--repo', type=str,
        help='Repository in format owner/repo (required for setup)'
    )
    parser.add_argument(
        '--max-prs', type=int,
        help='Maximum number of merged PRs to fetch (default 500)'
    )
    parser.add_argument(
        '--host', type=str,
        default=os.getenv('WEBHOOK_HOST', '0.0.0.0'),
        help='Host to bind webhook server to'
    )
    parser.add_argument(
        '--port', type=int,
        default=int(os.getenv('PORT', os.getenv('WEBHOOK_PORT', '5000'))),
        help='Port for webhook server'
    )
    parser.add_argument(
        '--debug', action='store_true', help='Enable debug mode'
    )

    args = parser.parse_args()

    if args.mode == 'setup' and not args.repo:
        parser.error("--repo is required for setup mode")

    try:
        if args.mode == 'setup':
            success = setup_mode(repo=args.repo, max_prs=args.max_prs)
            sys.exit(0 if success else 1)
        elif args.mode == 'webhook':
            webhook_mode(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
