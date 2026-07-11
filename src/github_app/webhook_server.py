"""
Webhook Server
Flask server to receive GitHub webhook events
"""

import os
import threading
from flask import Flask, request, jsonify
from dotenv import load_dotenv

from src.github_app.webhook_handler import WebhookHandler
from src.utils import get_logger, get_config

# Load environment
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Initialize components
config = get_config()
logger = get_logger(__name__)

# Get webhook secret
WEBHOOK_SECRET = os.getenv('GITHUB_WEBHOOK_SECRET')

# Shared secret protecting the /admin/setup endpoint (sent as X-Admin-Secret)
ADMIN_SECRET = os.getenv('ADMIN_SECRET')

# Initialize handler
handler = WebhookHandler(webhook_secret=WEBHOOK_SECRET)

logger.info("🌐 Webhook Server initialized")

@app.route('/admin/setup', methods=['POST'])
def trigger_setup():
    """Trigger setup for a repository (protected by ADMIN_SECRET)."""
    from app import setup_mode

    # Auth: if ADMIN_SECRET is configured, require a matching header.
    # Warn-and-allow if it is not set, so existing deployments keep working.
    if ADMIN_SECRET:
        provided = request.headers.get('X-Admin-Secret')
        if not provided or provided != ADMIN_SECRET:
            logger.warning("🚫 Rejected /admin/setup - missing/invalid X-Admin-Secret")
            return {"error": "unauthorized"}, 401
    else:
        logger.warning(
            "⚠️ ADMIN_SECRET not set - /admin/setup is UNPROTECTED. "
            "Set ADMIN_SECRET to prevent anyone from triggering setup."
        )

    data = request.get_json(silent=True) or {}
    repo = data.get('repo')  # Format: "owner/repo"
    installation_id = data.get('installation_id')  # Optional: use App auth instead of GITHUB_TOKEN
    force = bool(data.get('force', False))  # true = clear PR checkpoints and re-process everything

    if not repo:
        return {"error": "repo required in format owner/repo"}, 400

    # Run setup in background thread
    def run_setup():
        try:
            if force:
                from src.profile_generator.profile_storage import ProfileStorage
                ProfileStorage().clear_pr_checkpoints(repo)
            setup_mode(repo=repo, installation_id=installation_id)
            logger.info(f"Setup completed for {repo}")
        except Exception as e:
            logger.error(f"Setup failed for {repo}: {e}")

    threading.Thread(target=run_setup, daemon=True).start()

    return {"status": "setup started", "repo": repo, "force": force}, 202


    
@app.route('/webhook', methods=['POST'])
def webhook():
    """Main webhook endpoint"""
    
    # Get headers
    event_type = request.headers.get('X-GitHub-Event')
    signature = request.headers.get('X-Hub-Signature-256')
    delivery_id = request.headers.get('X-GitHub-Delivery')
    
    logger.info(f"📨 Incoming webhook: event={event_type}, delivery={delivery_id}")
    
    # Get payload
    payload = request.json
    payload_body = request.data

    if not payload:
        logger.error("❌ Empty payload received")
        return jsonify({'error': 'Empty payload'}), 400

    # 1. Verify signature SYNCHRONOUSLY so we can reject forged events with 401.
    if not handler.is_signature_valid(payload_body, signature):
        return jsonify({'status': 'error', 'message': 'Invalid signature'}), 401

    # 2. Process the event in a background thread and ACK immediately.
    #    GitHub requires a response within ~10s; LLM analysis + matching can
    #    take much longer, so doing it inline risks timeouts and webhook
    #    redelivery (which would create duplicate work). We return 202 now and
    #    let the worker post the suggestion when it finishes.
    def process_in_background():
        try:
            response = handler.handle_event(
                event_type=event_type,
                payload=payload,
                signature=signature,
                payload_body=payload_body
            )
            logger.info(
                f"✅ Webhook processed: status={response.get('status')}, "
                f"message={response.get('message')}"
            )
        except Exception as e:
            logger.error(f"❌ Background webhook processing failed: {e}")

    threading.Thread(target=process_in_background, daemon=True).start()

    return jsonify({'status': 'accepted', 'message': 'Processing in background'}), 202


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'GitHub Reviewer AI Webhook Server'
    }), 200


@app.route('/', methods=['GET'])
def index():
    """Root endpoint with info"""
    return jsonify({
        'service': 'GitHub Reviewer AI',
        'version': '1.0.0',
        'endpoints': {
            '/webhook': 'POST - GitHub webhook endpoint',
            '/health': 'GET - Health check',
            '/': 'GET - This info page'
        }
    }), 200


def run_server(host='0.0.0.0', port=5000, debug=False):
    """
    Run the webhook server
    
    Args:
        host: Host to bind to (0.0.0.0 = all interfaces)
        port: Port to listen on
        debug: Enable Flask debug mode
    """
    logger.info(f"🚀 Starting webhook server on {host}:{port}")
    
    if not WEBHOOK_SECRET:
        logger.warning("⚠️ GITHUB_WEBHOOK_SECRET not set - signature verification disabled")
    
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='GitHub Reviewer AI Webhook Server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to listen on')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("🤖 GITHUB REVIEWER AI - WEBHOOK SERVER".center(80))
    print("=" * 80)
    print()
    print(f"🌐 Server will run on: http://{args.host}:{args.port}")
    print(f"📡 Webhook endpoint: http://{args.host}:{args.port}/webhook")
    print(f"💚 Health check: http://{args.host}:{args.port}/health")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 80)
    print()
    
    run_server(host=args.host, port=args.port, debug=args.debug)