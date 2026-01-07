"""
PR Analyzer
Analyzes pull requests to extract technical requirements and needed expertise
"""

from typing import Dict, List, Optional
from pathlib import Path

from src.profile_generator.llm_client import LLMClient
from src.utils import get_logger, get_config

logger = get_logger(__name__)


class PRAnalyzer:
    """Analyzes PRs to determine reviewer requirements"""
    
    def __init__(self):
        """Initialize PR analyzer"""
        self.config = get_config()
        self.llm_client = LLMClient()
        logger.info("✅ PR Analyzer initialized")
    
    def analyze_pr(self, pr_data: Dict) -> Optional[Dict]:
        """
        Analyze PR and extract requirements
        
        Args:
            pr_data: Pull request data dictionary with keys:
                - pr_number (int)
                - title (str)
                - description (str)
                - author (dict with 'username')
                - repo_name (str)
                - changed_files (list of file paths)
                - additions (int)
                - deletions (int)
                - labels (list of strings)
        
        Returns:
            Dictionary with analysis results:
            {
                "technical_skills_needed": ["Node.js", "Express.js", ...],
                "expertise_areas_needed": ["Backend", "Testing"],
                "complexity_level": "Medium",
                "review_focus_areas": ["Code Quality", "Performance"],
                "primary_language": "JavaScript",
                "frameworks_involved": ["Express.js"]
            }
        """
        logger.info(f"🔍 Analyzing PR #{pr_data.get('pr_number')} - {pr_data.get('title', 'Untitled')}")
        
        try:
            # Build variables for prompt
            variables = self._build_analysis_variables(pr_data)
            
            # Load template and generate analysis
            template = self.llm_client.load_prompt_template('pr_requirements_analysis.txt')
            
            # Add format instructions for JSON output
            variables['format_instructions'] = """
Return ONLY a valid JSON object with no additional text, markdown, or explanation.
Example format:
{
  "technical_skills_needed": ["Node.js", "Express.js", "Jest"],
  "expertise_areas_needed": ["Backend", "Testing"],
  "complexity_level": "Medium",
  "review_focus_areas": ["Code Quality", "Testing Coverage"],
  "primary_language": "JavaScript",
  "frameworks_involved": ["Express.js", "Jest"]
}
"""
            
            # Generate analysis
            analysis = self.llm_client.generate(
                template,
                variables,
                parse_json=True
            )
            
            # Validate analysis
            if self._validate_analysis(analysis):
                logger.info(f"✅ PR analysis complete: {analysis.get('complexity_level')} complexity, "
                          f"{len(analysis.get('technical_skills_needed', []))} skills identified")
                return analysis
            else:
                logger.warning("⚠️ Analysis validation failed, returning None")
                return None
                
        except Exception as e:
            logger.error(f"❌ PR analysis failed: {e}")
            return None
    
    def _build_analysis_variables(self, pr_data: Dict) -> Dict:
        """
        Build variables for PR analysis prompt
        
        Args:
            pr_data: PR data dictionary
        
        Returns:
            Variables dictionary for prompt template
        """
        # Extract PR details
        pr_number = pr_data.get('pr_number', 0)
        title = pr_data.get('title', 'Untitled')
        description = pr_data.get('description', 'No description provided')
        author = pr_data.get('author', {}).get('username', 'Unknown') if pr_data.get('author') else 'Unknown'
        repo_name = pr_data.get('repo_name', 'Unknown Repository')
        
        # Changed files
        changed_files = pr_data.get('changed_files', [])
        changed_files_count = len(changed_files)
        
        # Format file list (limit to 20 files for prompt)
        if changed_files:
            files_list = '\n'.join(f"  - {f}" for f in changed_files[:20])
            if changed_files_count > 20:
                files_list += f"\n  ... and {changed_files_count - 20} more files"
        else:
            files_list = "  (No files listed)"
        
        # Code changes
        additions = pr_data.get('additions', 0)
        deletions = pr_data.get('deletions', 0)
        
        # Labels
        labels = pr_data.get('labels', [])
        labels_str = ', '.join(labels) if labels else 'None'
        
        # Build variables dictionary
        variables = {
            'repo_name': repo_name,
            'pr_number': pr_number,
            'pr_title': title,
            'pr_author': author,
            'pr_description': description[:1000] + ('...' if len(description) > 1000 else ''),
            'changed_files_count': changed_files_count,
            'files_changed': files_list,
            'additions': additions,
            'deletions': deletions,
            'labels': labels_str
        }
        
        return variables
    
    def _validate_analysis(self, analysis: Dict) -> bool:
        """
        Validate analysis results
        
        Args:
            analysis: Analysis dictionary
        
        Returns:
            True if valid, False otherwise
        """
        # Check required keys
        required_keys = [
            'technical_skills_needed',
            'expertise_areas_needed',
            'complexity_level',
            'review_focus_areas',
            'primary_language',
            'frameworks_involved'
        ]
        
        for key in required_keys:
            if key not in analysis:
                logger.warning(f"⚠️ Missing required key: {key}")
                return False
        
        # Validate complexity level
        valid_complexity = ['Low', 'Medium', 'High']
        if analysis['complexity_level'] not in valid_complexity:
            logger.warning(f"⚠️ Invalid complexity level: {analysis['complexity_level']}")
            return False
        
        # Validate data types
        list_keys = [
            'technical_skills_needed',
            'expertise_areas_needed',
            'review_focus_areas',
            'frameworks_involved'
        ]
        
        for key in list_keys:
            if not isinstance(analysis[key], list):
                logger.warning(f"⚠️ {key} should be a list")
                return False
        
        if not isinstance(analysis['primary_language'], str):
            logger.warning(f"⚠️ primary_language should be a string")
            return False
        
        logger.debug("✅ Analysis validation passed")
        return True
    
    def get_complexity_score(self, pr_data: Dict) -> str:
        """
        Quick complexity assessment without LLM (fallback)
        
        Args:
            pr_data: PR data
        
        Returns:
            Complexity level string
        """
        additions = pr_data.get('additions', 0)
        deletions = pr_data.get('deletions', 0)
        total_changes = additions + deletions
        changed_files = len(pr_data.get('changed_files', []))
        
        # Simple heuristic
        if total_changes < 50 or changed_files <= 2:
            return "Low"
        elif total_changes < 200 or changed_files <= 5:
            return "Medium"
        else:
            return "High"


# Example usage and testing
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("🔍 Testing PR Analyzer")
    print("=" * 60)
    
    # Sample PR data
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
        # Initialize analyzer
        analyzer = PRAnalyzer()
        print("✅ Analyzer initialized")
        
        # Analyze PR
        print("\n📊 Analyzing sample PR...")
        analysis = analyzer.analyze_pr(sample_pr)
        
        if analysis:
            print("\n✅ PR Analysis Results:")
            print("=" * 60)
            print(f"Complexity: {analysis['complexity_level']}")
            print(f"Primary Language: {analysis['primary_language']}")
            print(f"\nTechnical Skills Needed:")
            for skill in analysis['technical_skills_needed']:
                print(f"  - {skill}")
            print(f"\nExpertise Areas:")
            for area in analysis['expertise_areas_needed']:
                print(f"  - {area}")
            print(f"\nReview Focus:")
            for focus in analysis['review_focus_areas']:
                print(f"  - {focus}")
            print(f"\nFrameworks:")
            for fw in analysis['frameworks_involved']:
                print(f"  - {fw}")
            
            print("\n✅ PR Analyzer working correctly!")
        else:
            print("❌ Analysis failed")
            
    except ValueError as e:
        print(f"⚠️ Configuration error: {e}")
        print("Make sure OPENAI_API_KEY is set in .env file")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()