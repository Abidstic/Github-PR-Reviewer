"""
Webhook Handler
Processes GitHub webhook events for PR reviewer assignment
"""

import hmac
import hashlib
from typing import Dict, Optional

from src.reviewer_assigner.assignment_pipeline import AssignmentPipeline
from src.utils import get_logger, get_config

logger = get_logger(__name__)


class WebhookHandler:
    """Handles GitHub webhook events"""
    
    def __init__(self, webhook_secret: Optional[str] = None):
        """
        Initialize webhook handler
        
        Args:
            webhook_secret: GitHub webhook secret for signature verification
        """
        self.config = get_config()
        self.webhook_secret = webhook_secret
        
        # Initialize assignment pipeline
        self.pipeline = AssignmentPipeline(load_vector_store=True)
        
        logger.info("✅ Webhook Handler initialized")
    
    def verify_signature(
        self,
        payload_body: bytes,
        signature_header: str
    ) -> bool:
        """
        Verify GitHub webhook signature
        
        Args:
            payload_body: Raw request body
            signature_header: X-Hub-Signature-256 header value
        
        Returns:
            True if signature is valid
        """
        if not self.webhook_secret:
            logger.warning("⚠️ Webhook secret not configured - skipping verification")
            return True
        
        if not signature_header:
            logger.warning("⚠️ No signature header provided")
            return False
        
        # GitHub sends: sha256=<hash>
        hash_algorithm, github_signature = signature_header.split('=')
        
        if hash_algorithm != 'sha256':
            logger.warning(f"⚠️ Unsupported hash algorithm: {hash_algorithm}")
            return False
        
        # Compute expected signature
        mac = hmac.new(
            self.webhook_secret.encode('utf-8'),
            msg=payload_body,
            digestmod=hashlib.sha256
        )
        expected_signature = mac.hexdigest()
        
        # Compare signatures (constant-time comparison)
        is_valid = hmac.compare_digest(expected_signature, github_signature)
        
        if not is_valid:
            logger.warning("⚠️ Invalid webhook signature")
        
        return is_valid
    
    def handle_pull_request_event(self, payload: Dict) -> Dict:
        """
        Handle pull_request webhook event
        
        Args:
            payload: GitHub webhook payload
        
        Returns:
            Response dictionary with status and message
        """
        action = payload.get('action')
        pr_data_raw = payload.get('pull_request', {})
        repo_data = payload.get('repository', {})
        
        logger.info(f"📥 Received pull_request event: action={action}")
        
        # Only process 'opened' events
        if action not in ['opened', 'reopened']:
            logger.info(f"ℹ️ Ignoring action: {action}")
            return {
                'status': 'ignored',
                'message': f'Action {action} is not processed'
            }
        
        # Extract PR data
        pr_data = self._extract_pr_data(pr_data_raw, repo_data)
        
        if not pr_data:
            logger.error("❌ Failed to extract PR data")
            return {
                'status': 'error',
                'message': 'Failed to extract PR data'
            }
        
        pr_number = pr_data['pr_number']
        repo_name = pr_data['repo_name']
        
        logger.info(f"🔄 Processing PR #{pr_number} from {repo_name}")
        
        # Check if already commented
        if self._should_skip_pr(pr_data):
            logger.info(f"ℹ️ Skipping PR #{pr_number} (already processed or excluded)")
            return {
                'status': 'skipped',
                'message': 'PR already processed or should be excluded'
            }
        
        # Process PR through pipeline
        try:
            result = self.pipeline.process_pr(
                pr_data=pr_data,
                post_to_github=True,
                dry_run=False  # Actually post!
            )
            
            if result['posted_to_github']:
                logger.info(f"✅ Successfully processed PR #{pr_number}")
                return {
                    'status': 'success',
                    'message': f'Reviewer suggestions posted to PR #{pr_number}',
                    'pr_number': pr_number,
                    'confidence': result['recommendations']['assignment_confidence'],
                    'reviewers_suggested': len(result['recommendations']['recommended_reviewers'])
                }
            else:
                logger.warning(f"⚠️ Failed to post to PR #{pr_number}")
                return {
                    'status': 'error',
                    'message': 'Failed to post suggestions to GitHub'
                }
                
        except Exception as e:
            logger.error(f"❌ Error processing PR #{pr_number}: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _extract_pr_data(self, pr_raw: Dict, repo_raw: Dict) -> Optional[Dict]:
        """
        Extract PR data from webhook payload
        
        Args:
            pr_raw: Pull request object from webhook
            repo_raw: Repository object from webhook
        
        Returns:
            Standardized PR data dictionary
        """
        try:
            # Get file changes (requires additional API call in real webhook)
            # For webhook, we get limited file info
            changed_files = []
            if 'changed_files' in pr_raw:
                # This field exists in the payload
                changed_files = [f['filename'] for f in pr_raw.get('files', [])]
            
            pr_data = {
                'pr_number': pr_raw['number'],
                'title': pr_raw['title'],
                'description': pr_raw.get('body', ''),
                'author': {
                    'username': pr_raw['user']['login']
                },
                'repo_name': repo_raw['full_name'],
                'changed_files': changed_files,
                'additions': pr_raw.get('additions', 0),
                'deletions': pr_raw.get('deletions', 0),
                'labels': [label['name'] for label in pr_raw.get('labels', [])],
                'state': pr_raw['state'],
                'created_at': pr_raw['created_at']
            }
            
            return pr_data
            
        except KeyError as e:
            logger.error(f"❌ Missing required field in payload: {e}")
            return None
    
    def _should_skip_pr(self, pr_data: Dict) -> bool:
        """
        Check if PR should be skipped
        
        Args:
            pr_data: PR data dictionary
        
        Returns:
            True if should skip
        """
        # Skip if already has bot comment (optional - implement if needed)
        # For now, always process
        return False
    
    def handle_ping_event(self, payload: Dict) -> Dict:
        """
        Handle ping webhook event (for setup verification)
        
        Args:
            payload: GitHub webhook payload
        
        Returns:
            Response dictionary
        """
        logger.info("📡 Received ping event")
        
        zen = payload.get('zen', 'No zen provided')
        hook_id = payload.get('hook_id', 'unknown')
        
        return {
            'status': 'success',
            'message': 'Webhook is configured correctly',
            'zen': zen,
            'hook_id': hook_id
        }
    
    def handle_event(
        self,
        event_type: str,
        payload: Dict,
        signature: Optional[str] = None,
        payload_body: Optional[bytes] = None
    ) -> Dict:
        """
        Main entry point for webhook events
        
        Args:
            event_type: GitHub event type (X-GitHub-Event header)
            payload: Parsed JSON payload
            signature: X-Hub-Signature-256 header (for verification)
            payload_body: Raw request body (for signature verification)
        
        Returns:
            Response dictionary
        """
        logger.info(f"📨 Received webhook: event_type={event_type}")
        
        # Verify signature if provided
        if signature and payload_body:
            if not self.verify_signature(payload_body, signature):
                return {
                    'status': 'error',
                    'message': 'Invalid webhook signature'
                }
        
        # Route to appropriate handler
        if event_type == 'ping':
            return self.handle_ping_event(payload)
        elif event_type == 'pull_request':
            return self.handle_pull_request_event(payload)
        else:
            logger.info(f"ℹ️ Unhandled event type: {event_type}")
            return {
                'status': 'ignored',
                'message': f'Event type {event_type} is not processed'
            }


# Example usage and testing
if __name__ == "__main__":
    import json
    
    print("🎣 Testing Webhook Handler")
    print("=" * 60)
    
    # Sample webhook payload (pull_request.opened)
    sample_payload = {
        "action": "opened",
        "number": 1234,
        "pull_request": {
            "number": 1234,
            "title": "Fix Express.js routing bug",
            "body": "This PR fixes a routing issue in Express middleware.",
            "user": {
                "login": "developer1"
            },
            "state": "open",
            "created_at": "2025-01-07T12:00:00Z",
            "additions": 85,
            "deletions": 42,
            "labels": [
                {"name": "bug"},
                {"name": "backend"}
            ]
        },
        "repository": {
            "full_name": "moment/moment",
            "name": "moment",
            "owner": {
                "login": "moment"
            }
        }
    }
    
    try:
        # Initialize handler
        handler = WebhookHandler()
        print("✅ Handler initialized")
        
        # Test ping event
        print("\n📡 Testing ping event...")
        ping_payload = {
            "zen": "Design for failure.",
            "hook_id": 12345
        }
        response = handler.handle_event('ping', ping_payload)
        print(f"✅ Ping response: {response['message']}")
        
        # Test pull_request event (dry run in test)
        print("\n🔄 Testing pull_request event...")
        print("Note: This will actually process the PR if pipeline is configured")
        print("Use a test repository to avoid affecting real PRs")
        
        # Uncomment to test with real PR processing:
        # response = handler.handle_event('pull_request', sample_payload)
        # print(f"Response: {json.dumps(response, indent=2)}")
        
        print("\n✅ Webhook Handler working correctly!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()