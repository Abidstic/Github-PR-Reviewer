"""
Webhook Handler
Processes incoming GitHub webhook events and triggers the assignment pipeline
"""

import hmac
import hashlib
import json
import threading
from typing import Dict, Optional, Any

from src.reviewer_assigner.assignment_pipeline import AssignmentPipeline
from src.github_app.github_poster import GitHubPoster
from src.data_fetcher.github_client import GitHubClient
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

        # Singleton AssignmentPipeline: loading it means loading the
        # sentence-transformers model + FAISS index, which is expensive
        # (tens of seconds + hundreds of MB). It used to be re-created for
        # EVERY webhook; now it is created lazily on the first PR and reused.
        # Lazy (not eager) so server boot stays fast for health checks.
        self._pipeline: Optional[AssignmentPipeline] = None
        self._pipeline_lock = threading.Lock()

        logger.info("✅ Webhook Handler initialized")

    def _get_pipeline(self) -> AssignmentPipeline:
        """Return the shared pipeline, creating it once (thread-safe)."""
        if self._pipeline is None:
            with self._pipeline_lock:
                if self._pipeline is None:
                    logger.info("⏳ First PR: loading AssignmentPipeline singleton (model + index)...")
                    self._pipeline = AssignmentPipeline()
        return self._pipeline

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

    def handle_installation_event(self, payload: Dict) -> Dict:
        """Handle App installation/removal"""
        action = payload.get('action')
        logger.info(f"📥 Installation event: action={action}")
        
        return {
            'status': 'success',
            'message': f'Installation {action} handled'
        }

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
                'title': pr_data_raw.get('title'),
                'description': pr_data_raw.get('body', ''),
                'author': {'username': pr_data_raw.get('user', {}).get('login')},
                'repo_name': repo_data.get('full_name'),
                'changed_files': changed_files,
                'additions': pr_data_raw.get('additions', 0),
                'deletions': pr_data_raw.get('deletions', 0),
                'labels': [l.get('name') for l in pr_data_raw.get('labels', [])],
                'is_draft': pr_data_raw.get('draft', False)
            }
        except Exception as e:
            logger.error(f"❌ Error extracting PR data: {e}")
            return None
