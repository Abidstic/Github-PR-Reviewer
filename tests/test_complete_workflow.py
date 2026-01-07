"""
Complete Workflow Test
Tests the entire reviewer assignment system end-to-end
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.reviewer_assigner.assignment_pipeline import AssignmentPipeline
from src.utils import get_logger

logger = get_logger(__name__)


def print_section(title: str):
    """Print formatted section header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def test_complete_workflow():
    """Test complete end-to-end workflow"""
    
    print_section("🧪 GITHUB REVIEWER AI - COMPLETE WORKFLOW TEST")
    
    # Load environment
    load_dotenv()
    
    # Check prerequisites
    print("\n📋 Checking Prerequisites...")
    print("-" * 80)
    
    checks = {
        'GITHUB_TOKEN': os.getenv('GITHUB_TOKEN') is not None,
        'OPENAI_API_KEY': os.getenv('OPENAI_API_KEY') is not None,
        'Profiles exist': Path('data/profiles/reviewers').exists(),
        'Database exists': Path('data/cache/reviewers.db').exists()
    }
    
    for check, passed in checks.items():
        status = "✅" if passed else "❌"
        print(f"{status} {check}")
    
    if not all(checks.values()):
        print("\n⚠️ Some prerequisites missing. Results may be limited.")
    
    # Test PR scenarios
    test_scenarios = [
        {
            'name': 'Backend Bug Fix',
            'pr': {
                'pr_number': 1001,
                'title': 'Fix Express.js routing bug in API endpoints',
                'description': '''
Critical bug fix in Express middleware routing logic.
- Updated route matching in src/routes/api.js
- Added Jest unit tests
- Fixed middleware chain ordering
                ''',
                'author': {'username': 'developer1'},
                'repo_name': 'test/test-repo',
                'changed_files': [
                    'src/routes/api.js',
                    'test/routes/api.test.js',
                    'package.json'
                ],
                'additions': 85,
                'deletions': 42,
                'labels': ['bug', 'backend', 'high-priority']
            }
        },
        {
            'name': 'Frontend Feature',
            'pr': {
                'pr_number': 1002,
                'title': 'Add React component for data visualization',
                'description': '''
New feature: Interactive chart component using React and D3.js
- Created Chart component
- Added TypeScript types
- Implemented responsive design
                ''',
                'author': {'username': 'developer2'},
                'repo_name': 'test/test-repo',
                'changed_files': [
                    'src/components/Chart.tsx',
                    'src/components/Chart.test.tsx',
                    'src/types/chart.d.ts'
                ],
                'additions': 250,
                'deletions': 10,
                'labels': ['feature', 'frontend', 'visualization']
            }
        },
        {
            'name': 'Documentation Update',
            'pr': {
                'pr_number': 1003,
                'title': 'Update API documentation',
                'description': 'Updated README and API docs with new endpoint examples',
                'author': {'username': 'developer3'},
                'repo_name': 'test/test-repo',
                'changed_files': [
                    'README.md',
                    'docs/api.md'
                ],
                'additions': 30,
                'deletions': 15,
                'labels': ['documentation']
            }
        }
    ]
    
    # Initialize pipeline
    print_section("🚀 Initializing Assignment Pipeline")
    
    try:
        pipeline = AssignmentPipeline(load_vector_store=False)
        print("✅ Pipeline initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize pipeline: {e}")
        return False
    
    # Process each scenario
    results = []
    
    for scenario in test_scenarios:
        print_section(f"🔄 Test Scenario: {scenario['name']}")
        
        pr_data = scenario['pr']
        print(f"\n📝 PR #{pr_data['pr_number']}: {pr_data['title']}")
        print(f"👤 Author: {pr_data['author']['username']}")
        print(f"📊 Changes: +{pr_data['additions']} -{pr_data['deletions']} lines")
        print(f"🏷️  Labels: {', '.join(pr_data['labels'])}")
        
        try:
            # Process PR
            result = pipeline.process_pr(
                pr_data=pr_data,
                post_to_github=False,  # Don't actually post
                dry_run=True
            )
            
            # Display results
            print("\n" + "-" * 80)
            print("📊 RESULTS")
            print("-" * 80)
            
            if result['pr_requirements']:
                req = result['pr_requirements']
                print(f"\n✅ PR Analysis:")
                print(f"   • Complexity: {req['complexity_level']}")
                print(f"   • Primary Language: {req['primary_language']}")
                print(f"   • Skills Needed: {', '.join(req['technical_skills_needed'][:5])}")
                if len(req['technical_skills_needed']) > 5:
                    print(f"     ... and {len(req['technical_skills_needed']) - 5} more")
                print(f"   • Expertise Areas: {', '.join(req['expertise_areas_needed'])}")
            
            if result['recommendations']:
                recs = result['recommendations']
                reviewers = recs['recommended_reviewers']
                
                print(f"\n✅ Reviewer Matching:")
                print(f"   • Confidence: {recs['assignment_confidence']}")
                print(f"   • Found {len(reviewers)} reviewers")
                
                if reviewers:
                    print(f"\n   Top Recommendations:")
                    for i, rec in enumerate(reviewers[:3], 1):
                        print(f"   {i}. @{rec['reviewer_name']} ({rec['match_score']:.1%} match)")
                        print(f"      💡 {rec['reasoning'][:80]}...")
                else:
                    print(f"   ⚠️ No suitable reviewers found")
            
            results.append({
                'scenario': scenario['name'],
                'success': True,
                'reviewers_found': len(result['recommendations']['recommended_reviewers']) if result['recommendations'] else 0,
                'confidence': result['recommendations']['assignment_confidence'] if result['recommendations'] else 'N/A'
            })
            
            print("\n✅ Scenario processed successfully")
            
        except Exception as e:
            print(f"\n❌ Scenario failed: {e}")
            results.append({
                'scenario': scenario['name'],
                'success': False,
                'error': str(e)
            })
    
    # Summary
    print_section("📊 TEST SUMMARY")
    
    successful = sum(1 for r in results if r['success'])
    total = len(results)
    
    print(f"\n✅ Successful: {successful}/{total}")
    print(f"❌ Failed: {total - successful}/{total}")
    
    print("\n" + "-" * 80)
    print("Detailed Results:")
    print("-" * 80)
    
    for result in results:
        status = "✅" if result['success'] else "❌"
        print(f"\n{status} {result['scenario']}")
        if result['success']:
            print(f"   • Reviewers found: {result['reviewers_found']}")
            print(f"   • Confidence: {result['confidence']}")
        else:
            print(f"   • Error: {result.get('error', 'Unknown')}")
    
    # Final verdict
    print_section("🎉 FINAL VERDICT")
    
    if successful == total:
        print("\n✅ ALL TESTS PASSED!")
        print("The complete reviewer assignment system is working correctly.")
        print("\nNext steps:")
        print("1. Create vector store from historical data")
        print("2. Test with real GitHub PRs")
        print("3. Set up webhook for automated suggestions")
        return True
    else:
        print("\n⚠️ SOME TESTS FAILED")
        print("Please check the errors above and fix any issues.")
        return False


if __name__ == "__main__":
    print("\n" + "🤖 GITHUB REVIEWER AI".center(80))
    print("Complete System Test".center(80))
    print()
    
    success = test_complete_workflow()
    
    sys.exit(0 if success else 1)