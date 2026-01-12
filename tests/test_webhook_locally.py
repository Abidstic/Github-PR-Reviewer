"""
Test Webhook Locally
Simulates GitHub webhook events for local testing
"""

import json
import requests
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv() 

def test_webhook_server(base_url='http://localhost:5000'):
    """Test webhook server with sample payloads"""
    
    print("🧪 Testing Webhook Server")
    print("=" * 80)
    print(f"Target: {base_url}")
    print()
    
    # Test 1: Health check
    print("1️⃣ Testing health endpoint...")
    try:
        response = requests.get(f"{base_url}/health")
        if response.status_code == 200:
            print(f"   ✅ Health check passed: {response.json()}")
        else:
            print(f"   ❌ Health check failed: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("   ❌ Server not running. Start it with:")
        print("      python3 src/github_app/webhook_server.py")
        return False
    
    time.sleep(0.5)
    
    # Test 2: Root endpoint
    print("\n2️⃣ Testing root endpoint...")
    response = requests.get(f"{base_url}/")
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Service: {data['service']}")
        print(f"   ✅ Version: {data['version']}")
    
    time.sleep(0.5)
    
    # Test 3: Ping event
    print("\n3️⃣ Testing ping webhook...")
    ping_payload = {
        "zen": "Design for failure.",
        "hook_id": 12345,
        "hook": {
            "type": "Repository",
            "id": 12345,
            "events": ["pull_request"]
        }
    }
    
    headers = {
        'X-GitHub-Event': 'ping',
        'X-GitHub-Delivery': 'test-delivery-123',
        'Content-Type': 'application/json'
    }
    
    response = requests.post(
        f"{base_url}/webhook",
        json=ping_payload,
        headers=headers
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Ping successful: {data.get('message')}")
        print(f"   📖 Zen: {data.get('zen')}")
    else:
        print(f"   ❌ Ping failed: {response.status_code}")
        print(f"   Response: {response.text}")
    
    time.sleep(0.5)
    
    # Test 4: Pull request opened event
    print("\n4️⃣ Testing pull_request.opened webhook...")
    print("   ⚠️  This will trigger the full pipeline!")
    print("   ⚠️  Make sure you're using a test repository")
    
    input("   Press Enter to continue or Ctrl+C to skip...")
    
    pr_payload = {
        "action": "opened",
        "number": 909999,
        "pull_request": {
            "id": 1,
            "number": 1,
            "state": "open",
            "title": "Test: Add comment for reviewer AI testing",
            "body": "This is a test PR to validate the reviewer AI system.",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "user": {
                "login": "test-developer",
                "id": 1
            },
            "labels": [
                {"name": "test"},
                {"name": "documentation"}
            ],
            "additions": 5,
            "deletions": 2,
            "changed_files": 1
        },
        "repository": {
            "id": 1,
            "name": "express",
            "full_name": "Abidstic/express", 
            "owner": {
                "login": "Abidstic", 
                "id": 1
            }
        }
    }
    
    headers = {
        'X-GitHub-Event': 'pull_request',
        'X-GitHub-Delivery': 'test-delivery-456',
        'Content-Type': 'application/json'
    }
    
    response = requests.post(
        f"{base_url}/webhook",
        json=pr_payload,
        headers=headers
    )
    
    print(f"\n   📨 Response Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Status: {data.get('status')}")
        print(f"   💬 Message: {data.get('message')}")
        
        if 'confidence' in data:
            print(f"   🎯 Confidence: {data.get('confidence')}")
        if 'reviewers_suggested' in data:
            print(f"   👥 Reviewers suggested: {data.get('reviewers_suggested')}")
    else:
        print(f"   ❌ Request failed")
        print(f"   Response: {response.text}")
    
    # Summary
    print("\n" + "=" * 80)
    print("✅ Webhook server testing complete!")
    print("=" * 80)
    
    return True


if __name__ == '__main__':
    print("\n🤖 GITHUB REVIEWER AI".center(80))
    print("Webhook Server Test".center(80))
    print()
    
    print("⚠️  BEFORE RUNNING THIS TEST:")
    print("1. Start the webhook server:")
    print("   python3 src/github_app/webhook_server.py")
    print()
    print("2. Update the test payload with your repository name")
    print("   (Edit this file and change YOUR_USERNAME)")
    print()
    
    input("Press Enter when ready to test...")
    print()
    
    test_webhook_server()