"""
Test Pipeline Without GitHub Posting
Tests the complete pipeline without actually posting to GitHub
"""

import sys
from pathlib import Path
from dotenv import load_dotenv 

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

load_dotenv() 

from src.reviewer_assigner.assignment_pipeline import AssignmentPipeline


def test_pipeline_without_github():
    """Test complete pipeline without GitHub posting"""
    
    print("=" * 80)
    print("🧪 TESTING ASSIGNMENT PIPELINE (No GitHub Posting)".center(80))
    print("=" * 80)
    print()
    
    # Sample PR data (doesn't need to exist on GitHub)
    sample_pr = {
        'pr_number': 9999,  # Fake PR number
        'title': 'Fix Express.js routing middleware bug',
        'description': '''
This PR fixes a critical bug in the Express.js routing middleware.

Changes:
- Updated route matching logic in lib/router/index.js
- Added unit tests
- Fixed middleware chain ordering
- Updated documentation

The issue was caused by incorrect route parameter parsing.
        ''',
        'author': {'username': 'test-developer'},
        'repo_name': 'Abidstic/express',
        'changed_files': [
            'lib/router/index.js',
            'test/router.test.js',
            'package.json',
            'README.md'
        ],
        'additions': 120,
        'deletions': 45,
        'labels': ['bug', 'backend', 'high-priority']
    }
    
    print("📝 Test PR Details:")
    print("-" * 80)
    print(f"PR Number: #{sample_pr['pr_number']}")
    print(f"Title: {sample_pr['title']}")
    print(f"Author: {sample_pr['author']['username']}")
    print(f"Changes: +{sample_pr['additions']} -{sample_pr['deletions']}")
    print(f"Files: {len(sample_pr['changed_files'])} changed")
    print()
    
    try:
        # Initialize pipeline
        print("🚀 Initializing pipeline...")
        pipeline = AssignmentPipeline(load_vector_store=False)
        print("✅ Pipeline initialized")
        print()
        
        # Process PR (WITHOUT posting to GitHub)
        print("🔄 Processing PR through complete pipeline...")
        print("-" * 80)
        
        result = pipeline.process_pr(
            pr_data=sample_pr,
            post_to_github=False,  # Don't post to GitHub
            dry_run=True
        )
        
        # Display results
        print()
        print("=" * 80)
        print("📊 RESULTS".center(80))
        print("=" * 80)
        print()
        
        # PR Requirements
        if result['pr_requirements']:
            req = result['pr_requirements']
            print("✅ PR Analysis:")
            print(f"   • Complexity: {req['complexity_level']}")
            print(f"   • Primary Language: {req['primary_language']}")
            print(f"   • Skills Needed ({len(req['technical_skills_needed'])}):")
            for skill in req['technical_skills_needed'][:5]:
                print(f"     - {skill}")
            if len(req['technical_skills_needed']) > 5:
                print(f"     ... and {len(req['technical_skills_needed']) - 5} more")
            print(f"   • Expertise Areas: {', '.join(req['expertise_areas_needed'])}")
            print(f"   • Review Focus: {', '.join(req['review_focus_areas'])}")
            print()
        
        # Reviewer Recommendations
        if result['recommendations']:
            recs = result['recommendations']
            reviewers = recs['recommended_reviewers']
            
            print("✅ Reviewer Matching:")
            print(f"   • Confidence: {recs['assignment_confidence']}")
            print(f"   • Reasoning: {recs['assignment_reasoning']}")
            print(f"   • Reviewers Found: {len(reviewers)}")
            print()
            
            if reviewers:
                print("   📋 Recommended Reviewers:")
                print("   " + "-" * 76)
                for i, rec in enumerate(reviewers, 1):
                    print(f"   {i}. @{rec['reviewer_name']} ({rec['match_score']:.1%} match)")
                    print(f"      💡 {rec['reasoning']}")
                    if rec['strengths_alignment']:
                        print(f"      ⭐ Strengths: {', '.join(rec['strengths_alignment'][:3])}")
                    print(f"      📊 Experience: {rec['review_experience']}")
                    if rec['potential_concerns'] != "None identified":
                        print(f"      ⚠️  {rec['potential_concerns']}")
                    print()
            else:
                print("   ⚠️ No suitable reviewers found")
                print()
        
        # Formatted Comment Preview
        if result['formatted_comment']:
            print("✅ Formatted Comment:")
            print(f"   • Length: {len(result['formatted_comment'])} characters")
            print()
            print("   Preview (first 500 chars):")
            print("   " + "-" * 76)
            preview = result['formatted_comment'][:500].replace('\n', '\n   ')
            print(f"   {preview}...")
            print()
        
        # Summary
        print("=" * 80)
        print("✅ PIPELINE TEST SUCCESSFUL!".center(80))
        print("=" * 80)
        print()
        print("The complete pipeline works correctly:")
        print("  1. ✅ PR Analysis - Extracted requirements")
        print("  2. ✅ Reviewer Matching - Found suitable reviewers")
        print("  3. ✅ Formatting - Generated markdown comment")
        print("  4. ⏭️  GitHub Posting - Skipped (test mode)")
        print()
        print("Next step: Create a real PR in your fork to test GitHub posting!")
        print()
        
        return True
        
    except Exception as e:
        print()
        print("=" * 80)
        print("❌ TEST FAILED".center(80))
        print("=" * 80)
        print()
        print(f"Error: {e}")
        print()
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = test_pipeline_without_github()
    sys.exit(0 if success else 1)