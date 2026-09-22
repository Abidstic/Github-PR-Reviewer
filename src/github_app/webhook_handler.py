"""
Webhook Handler
Processes incoming GitHub webhook events and triggers the assignment pipeline.

Phase 4 additions: handles pull_request.closed (merged) events to feed the
rolling window and update unified profiles via LLM.
"""

import hmac
import hashlib
import json
import threading
from typing import Dict, List, Optional, Any

from src.reviewer_assigner.assignment_pipeline import AssignmentPipeline
from src.github_app.github_poster import GitHubPoster
from src.data_fetcher.github_client import GitHubClient
from src.storage.window_manager import WindowManager
from src.utils import get_logger, get_config

logger = get_logger(__name__)


class WebhookHandler:
    """Handles GitHub webhook events"""

    def __init__(self, webhook_secret: Optional[str] = None):
        """
        Initialize webhook handler

        Args:
            webhook_secret: Secret for verifying GitHub signatures
        """
        self.config = get_config()
        self.webhook_secret = webhook_secret

        # Rolling window manager (lightweight — just SQLite)
        self._window_manager = WindowManager()

        # Singleton AssignmentPipeline: loading it means loading the
        # sentence-transformers model + FAISS index, which is expensive
        # (tens of seconds + hundreds of MB). It used to be re-created for
        # EVERY webhook; now it is created lazily on the first PR and reused.
        # Lazy (not eager) so server boot stays fast for health checks.
        self._pipeline: Optional[AssignmentPipeline] = None
        self._pipeline_lock = threading.Lock()

        # Lazy-loaded UnifiedProfileBuilder (needs LLM client — expensive)
        self._profile_builder = None
        self._profile_builder_lock = threading.Lock()

        # Repos currently being auto-indexed, and PRs that arrived during
        # indexing (queued for replay once indexing completes). In-memory:
        # lost on restart, in which case close/reopen the PR re-triggers it.
        self._indexing_repos: set = set()
        self._pending_prs: Dict[str, list] = {}
        self._state_lock = threading.Lock()

        logger.info("✅ Webhook Handler initialized")

    def _get_pipeline(self) -> AssignmentPipeline:
        """Return the shared pipeline, creating it once (thread-safe)."""
        if self._pipeline is None:
            with self._pipeline_lock:
                if self._pipeline is None:
                    logger.info("⏳ First PR: loading AssignmentPipeline singleton (model + index)...")
                    self._pipeline = AssignmentPipeline(
                        window_manager=self._window_manager
                    )
        return self._pipeline

    def _get_profile_builder(self):
        """Return the shared UnifiedProfileBuilder, creating it once (thread-safe)."""
        if self._profile_builder is None:
            with self._profile_builder_lock:
                if self._profile_builder is None:
                    from src.profile_generator.unified_profile_builder import UnifiedProfileBuilder
                    logger.info("⏳ Loading UnifiedProfileBuilder (LLM client)...")
                    self._profile_builder = UnifiedProfileBuilder(
                        window_manager=self._window_manager
                    )
        return self._profile_builder

    def handle_event(
        self, 
        event_type: str, 
        payload: Dict, 
        signature: Optional[str] = None,
        payload_body: Optional[bytes] = None
    ) -> Dict:
        """Route and handle incoming event"""
        # Verify signature if secret is provided
        if self.webhook_secret and signature:
            if not self._verify_signature(payload_body, signature):
                logger.error("❌ Invalid webhook signature")
                return {'status': 'error', 'message': 'Invalid signature'}
        
        installation_id = payload.get('installation', {}).get('id')
        logger.info(f"📨 Received webhook: event_type={event_type}, installation_id={installation_id}")
        
        # Route to specific handler
        if event_type == 'pull_request':
            return self.handle_pull_request_event(payload, installation_id)
        elif event_type == 'installation':
            return self.handle_installation_event(payload)
        elif event_type == 'installation_repositories':
            return self.handle_installation_repositories_event(payload)
        elif event_type == 'ping':
            return self.handle_ping_event(payload)
        else:
            logger.info(f"ℹ️ Ignoring event type: {event_type}")
            return {
                'status': 'ignored',
                'message': f'Event type {event_type} is not processed'
            }

    def is_signature_valid(self, payload_body: bytes, signature: Optional[str]) -> bool:
        """
        Public signature check used by the route before accepting a webhook.

        Behaviour (warn-and-allow):
        - If no webhook secret is configured, log a loud warning and ALLOW the
          request (keeps an existing deployment working until the secret is set).
        - If a secret IS configured, require a valid signature.
        """
        if not self.webhook_secret:
            logger.warning(
                "⚠️ GITHUB_WEBHOOK_SECRET not set - accepting webhook WITHOUT "
                "signature verification. Set it in production to reject forged events."
            )
            return True

        if not signature:
            logger.error("❌ Webhook secret is configured but request has no signature")
            return False

        return self._verify_signature(payload_body, signature)

    def _verify_signature(self, payload_body: bytes, signature: str) -> bool:
        """Verify GitHub webhook signature"""
        if not self.webhook_secret or not signature:
            return True
            
        if signature.startswith('sha256='):
            signature = signature[7:]
            
        hash_object = hmac.new(
            self.webhook_secret.encode('utf-8'),
            msg=payload_body,
            digestmod=hashlib.sha256
        )
        expected_signature = hash_object.hexdigest()
        
        return hmac.compare_digest(expected_signature, signature)

    def handle_pull_request_event(self, payload: Dict, installation_id: Optional[int] = None) -> Dict:
        """Process pull_request event"""
        action = payload.get('action')
        pr_data_raw = payload.get('pull_request', {})
        repo_data = payload.get('repository', {})

        logger.info(f"📥 Received pull_request event: action={action}")

        # Handle merged PRs (closed + merged=true)
        if action == 'closed' and pr_data_raw.get('merged', False):
            return self._handle_pr_merged(pr_data_raw, repo_data, installation_id)

        if action not in ['opened', 'reopened']:
            return {'status': 'ignored', 'message': f'Action {action} is not processed'}

        if pr_data_raw.get('draft', False):
            return {'status': 'skipped', 'message': 'Draft PRs are not processed'}

        # Create an installation-specific GitHub client to fetch PR files
        github_client = GitHubClient(installation_id=installation_id)
        pr_data = self._extract_pr_data(pr_data_raw, repo_data, github_client)
        
        if not pr_data:
            return {'status': 'error', 'message': 'Failed to extract PR data'}
        
        pr_number = pr_data['pr_number']
        repo_name = pr_data['repo_name']
        logger.info(f"🔄 Processing PR #{pr_number} from {repo_name}")

        # If this repo is still being indexed, don't run a doomed matching
        # pass. Post a placeholder comment and queue the PR - it will be
        # processed automatically when indexing completes (the suggestion
        # then EDITS the placeholder in place via the dedup guard).
        with self._state_lock:
            still_indexing = repo_name in self._indexing_repos
            if still_indexing:
                self._pending_prs.setdefault(repo_name, []).append((pr_data, installation_id))

        if still_indexing:
            logger.info(f"⏳ {repo_name} is still indexing - queueing PR #{pr_number} for replay")
            self._post_indexing_placeholder(pr_data, installation_id)
            return {'status': 'queued', 'message': f'Repo is indexing; PR #{pr_number} queued for replay'}

        try:
            # Reuse the shared pipeline (model + FAISS loaded once, not per PR)
            pipeline = self._get_pipeline()

            # Build a per-request poster with this installation's token so
            # posting works on any repo the App is installed on. Passed into
            # process_pr (instead of mutating the shared pipeline) to stay
            # thread-safe under concurrent webhooks. Falls back to the
            # pipeline's default poster (GITHUB_TOKEN) if App auth fails.
            poster = None
            if installation_id:
                try:
                    poster = GitHubPoster(installation_id=installation_id)
                except Exception as e:
                    logger.warning(f"⚠️ Installation auth failed, falling back to GITHUB_TOKEN: {e}")

            pipeline.process_pr(pr_data=pr_data, post_to_github=True, dry_run=False, github_poster=poster)
            return {'status': 'success', 'message': f'Suggestions posted to PR #{pr_number}', 'repo': repo_name, 'pr': pr_number}
        except Exception as e:
            logger.error(f"❌ Pipeline failed: {e}")
            return {'status': 'error', 'message': f'Failed to process PR: {str(e)}'}

    # ------------------------------------------------------------------
    # PR Merged handler (Phase 4 — rolling window)
    # ------------------------------------------------------------------

    def _handle_pr_merged(self, pr_data_raw: Dict, repo_data: Dict,
                          installation_id: Optional[int]) -> Dict:
        """
        Process a merged PR: add to rolling window, update profiles, evict.

        This is the new Phase 4 handler for pull_request.closed (merged=true).
        """
        pr_number = pr_data_raw.get('number')
        repo_full_name = repo_data.get('full_name', '')

        logger.info(f"🔀 PR #{pr_number} merged in {repo_full_name}")

        # Skip if already in window (webhook redelivery)
        if self._window_manager.is_pr_in_window(repo_full_name, pr_number):
            logger.info(f"PR #{pr_number} already in window — skipping")
            return {'status': 'skipped', 'message': 'PR already in window'}

        # Ensure repo is registered
        is_fork = repo_data.get('fork', False)
        parent_repo = None
        if is_fork and repo_data.get('parent'):
            parent_repo = repo_data['parent'].get('full_name')
        self._window_manager.init_repo(repo_full_name, is_fork, parent_repo)

        # Build GitHub client for this installation
        github_client = GitHubClient(installation_id=installation_id)

        try:
            owner, repo_name = repo_full_name.split('/')
        except ValueError:
            logger.error(f"Invalid repo name: {repo_full_name}")
            return {'status': 'error', 'message': 'Invalid repo name'}

        # Fetch file list, reviews, and review comments from GitHub API
        files = github_client.get_pr_files(owner, repo_name, pr_number)
        changed_files = [f.get('filename') for f in (files or [])]

        raw_reviews = github_client.get_pr_reviews(
            owner, repo_name, pr_number
        ) or []
        raw_review_comments = github_client.get_pr_review_comments(
            owner, repo_name, pr_number
        ) or []

        # Transform payload + API data into WindowManager format
        pr_data = self._extract_merged_pr_data(
            pr_data_raw, repo_full_name, changed_files
        )
        reviews = self._transform_reviews(raw_reviews)
        review_comments = self._transform_review_comments(raw_review_comments)

        # Add to rolling window
        pr_window_id = self._window_manager.add_pr(
            pr_data, reviews, review_comments
        )

        if pr_window_id is None:
            return {'status': 'skipped', 'message': 'PR not added (duplicate)'}

        # Evict oldest if window exceeds max size
        evicted = self._window_manager.evict_if_full(repo_full_name)
        if evicted:
            logger.info(
                f"Evicted PR #{evicted['pr_number']} to maintain window size"
            )

        # Update profiles in background (LLM calls are slow)
        def update_profiles_bg():
            try:
                builder = self._get_profile_builder()
                results = builder.update_profiles_for_merged_pr(
                    pr_window_id, repo_full_name
                )
                succeeded = sum(1 for v in results.values() if v)
                logger.info(
                    f"✅ Profile updates for PR #{pr_number}: "
                    f"{succeeded}/{len(results)} succeeded"
                )
            except Exception as e:
                logger.error(
                    f"❌ Profile update failed for PR #{pr_number}: {e}"
                )

        threading.Thread(target=update_profiles_bg, daemon=True).start()

        return {
            'status': 'success',
            'message': f'PR #{pr_number} added to window (id={pr_window_id})',
            'repo': repo_full_name,
            'pr': pr_number,
            'window_id': pr_window_id,
        }

    @staticmethod
    def _extract_merged_pr_data(pr_raw: Dict, repo_full_name: str,
                                 changed_files: List[str]) -> Dict:
        """Transform GitHub webhook PR payload into WindowManager format."""
        return {
            'repo_name': repo_full_name,
            'pr_number': pr_raw.get('number'),
            'title': pr_raw.get('title') or '',
            'description': pr_raw.get('body') or '',
            'author_username': pr_raw.get('user', {}).get('login', ''),
            'author_id': pr_raw.get('user', {}).get('id'),
            'created_at': pr_raw.get('created_at'),
            'merged_at': pr_raw.get('merged_at'),
            'additions': pr_raw.get('additions', 0),
            'deletions': pr_raw.get('deletions', 0),
            'changed_files': changed_files,
            'changed_files_count': len(changed_files),
            'labels': [l.get('name') for l in pr_raw.get('labels', [])],
        }

    @staticmethod
    def _transform_reviews(raw_reviews: List[Dict]) -> List[Dict]:
        """Transform GitHub API review objects into WindowManager format."""
        return [
            {
                'reviewer_username': r.get('user', {}).get('login', ''),
                'reviewer_id': r.get('user', {}).get('id'),
                'review_state': r.get('state', ''),
                'review_body': r.get('body') or '',
                'submitted_at': r.get('submitted_at'),
                'author_association': r.get('author_association'),
            }
            for r in raw_reviews
            if r.get('user')
        ]

    @staticmethod
    def _transform_review_comments(raw_comments: List[Dict]) -> List[Dict]:
        """Transform GitHub API review comment objects into WindowManager format."""
        return [
            {
                'reviewer_username': c.get('user', {}).get('login', ''),
                'reviewer_id': c.get('user', {}).get('id'),
                'body': c.get('body') or '',
                'file_path': c.get('path', ''),
                'line_number': c.get('line') or c.get('original_line'),
                'submitted_at': c.get('created_at'),
                'author_association': c.get('author_association'),
            }
            for c in raw_comments
            if c.get('user')
        ]

    def handle_installation_event(self, payload: Dict) -> Dict:
        """
        Handle App installation/removal.

        On 'created' (user installs the app), automatically index the selected
        repositories so the app works without any manual /admin/setup call.
        """
        action = payload.get('action')
        installation_id = payload.get('installation', {}).get('id')
        logger.info(f"📥 Installation event: action={action}")

        if action == 'created':
            repos = [r.get('full_name') for r in payload.get('repositories', []) if r.get('full_name')]
            if repos:
                self._start_auto_setup(repos, installation_id)
                return {
                    'status': 'success',
                    'message': f'Installation created - auto-setup started for {len(repos)} repo(s)'
                }

        return {
            'status': 'success',
            'message': f'Installation {action} handled'
        }

    def handle_installation_repositories_event(self, payload: Dict) -> Dict:
        """
        Handle repos being added/removed from an existing installation.

        On 'added', automatically index the newly added repositories.
        """
        action = payload.get('action')
        installation_id = payload.get('installation', {}).get('id')
        logger.info(f"📥 Installation repositories event: action={action}")

        if action == 'added':
            repos = [r.get('full_name') for r in payload.get('repositories_added', []) if r.get('full_name')]
            if repos:
                self._start_auto_setup(repos, installation_id)
                return {
                    'status': 'success',
                    'message': f'Auto-setup started for {len(repos)} added repo(s)'
                }

        return {
            'status': 'success',
            'message': f'Installation repositories {action} handled'
        }

    def _start_auto_setup(self, repos: list, installation_id: Optional[int]) -> None:
        """
        Index repositories in a background thread (sequentially, to avoid
        concurrent FAISS index writes and duplicate LLM spend).

        Idempotent: repos that already have reviewer profiles are skipped, so
        webhook redeliveries don't re-index (and re-pay for) the same repo.
        Manual re-indexing is still available via POST /admin/setup.
        """
        # Mark all repos as "indexing" up-front so PRs opened on any of them
        # while the (sequential) setup runs get queued instead of failing.
        with self._state_lock:
            self._indexing_repos.update(repos)

        def run():
            from app import setup_mode

            max_prs = self.config.get('github.auto_setup_max_prs', None)

            for repo in repos:
                try:
                    if self._window_manager.get_window_size(repo) > 0:
                        logger.info(f"⏭️ {repo} already indexed - skipping auto-setup")
                    else:
                        logger.info(f"🚀 Auto-setup starting for {repo} ({max_prs or 'ALL'} PRs)")
                        setup_mode(repo=repo, max_prs=max_prs, installation_id=installation_id)
                        logger.info(f"✅ Auto-setup completed for {repo}")
                except Exception as e:
                    logger.error(f"❌ Auto-setup failed for {repo}: {e}")
                finally:
                    with self._state_lock:
                        self._indexing_repos.discard(repo)
                        pending = self._pending_prs.pop(repo, [])
                    self._replay_pending_prs(repo, pending)

        threading.Thread(target=run, daemon=True).start()

    def _post_indexing_placeholder(self, pr_data: Dict, installation_id: Optional[int]) -> None:
        """
        Immediately tell the PR author that indexing is in progress. Uses the
        same bot_identifier header as real suggestions, so the replayed
        suggestion later EDITS this comment instead of adding a second one.
        """
        body = (
            "## 🤖 AI-Powered Reviewer Suggestions\n\n"
            "⏳ **ReviewerMatch is still indexing this repository's review history.**\n\n"
            "Reviewer suggestions will appear here automatically once indexing "
            "completes (usually a few minutes after installation)."
        )
        try:
            poster = GitHubPoster(installation_id=installation_id)
            poster.update_existing_comment(
                repo_full_name=pr_data['repo_name'],
                pr_number=pr_data['pr_number'],
                comment_body=body,
                dry_run=False
            )
            logger.info(f"💬 Posted indexing placeholder on PR #{pr_data['pr_number']}")
        except Exception as e:
            logger.warning(f"⚠️ Could not post indexing placeholder: {e}")

    def _replay_pending_prs(self, repo: str, pending: list) -> None:
        """Process PRs that arrived while their repo was being indexed."""
        if not pending:
            return

        logger.info(f"▶️ Replaying {len(pending)} queued PR(s) for {repo}")

        # The pipeline singleton may have been created BEFORE the FAISS index
        # existed - reload the vector store so similarity matching works.
        if self._pipeline is not None:
            try:
                self._pipeline.similarity_matcher.load_vector_store("reviewer_vectors.faiss")
                logger.info("🔄 Reloaded vector store after indexing")
            except Exception as e:
                logger.warning(f"⚠️ Could not reload vector store: {e}")

        for pr_data, inst_id in pending:
            pr_number = pr_data.get('pr_number')
            try:
                pipeline = self._get_pipeline()

                poster = None
                if inst_id:
                    try:
                        poster = GitHubPoster(installation_id=inst_id)
                    except Exception as e:
                        logger.warning(f"⚠️ Installation auth failed, falling back to GITHUB_TOKEN: {e}")

                pipeline.process_pr(pr_data=pr_data, post_to_github=True, dry_run=False, github_poster=poster)
                logger.info(f"✅ Replayed queued PR #{pr_number} ({repo})")
            except Exception as e:
                logger.error(f"❌ Failed to replay queued PR #{pr_number} ({repo}): {e}")

    def handle_ping_event(self, payload: Dict) -> Dict:
        """Handle webhook ping test"""
        logger.info("📡 Received ping event")
        return {
            'status': 'success',
            'message': 'Webhook is configured correctly',
            'zen': payload.get('zen', 'No zen provided'),
            'hook_id': payload.get('hook_id', 'unknown')
        }

    def _extract_pr_data(self, pr_data_raw: Dict, repo_data: Dict, github_client: GitHubClient) -> Optional[Dict]:
        """Extract needed fields from GitHub PR payload"""
        try:
            pr_number = pr_data_raw.get('number')
            owner = repo_data.get('owner', {}).get('login')
            repo = repo_data.get('name')
            
            logger.info(f"🔍 Fetching file changes for PR #{pr_number}")
            files = github_client.get_pr_files(owner, repo, pr_number)
            changed_files = [f.get('filename') for f in files] if files else []
            logger.info(f"✅ Found {len(changed_files)} changed files")

            return {
                'pr_number': pr_number,
                'title': pr_data_raw.get('title') or '',
                # .get('body', '') still returns None when body is null in the
                # payload (PRs with no description) - normalize to ''
                'description': pr_data_raw.get('body') or '',
                'author': {'username': pr_data_raw.get('user', {}).get('login')},
                'repo_name': repo_data.get('full_name'),
                'changed_files': changed_files,
                'additions': pr_data_raw.get('additions', 0),
                'deletions': pr_data_raw.get('deletions', 0),
                'labels': [l.get('name') for l in pr_data_raw.get('labels', [])],
                'is_draft': pr_data_raw.get('draft', False),
                # Fork repos get profiles built from the PARENT's reviewers.
                # The formatter uses this to avoid @-mentioning those people
                # (they have no relation to the fork and would get notified).
                'is_fork': repo_data.get('fork', False)
            }
        except Exception as e:
            logger.error(f"❌ Error extracting PR data: {e}")
            return None
