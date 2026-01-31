"""
Developer Profile Builder
Generates AI-powered profiles for PR authors/developers
"""

from typing import Dict, Optional
from pathlib import Path

from src.profile_generator.llm_client import LLMClient
from src.utils import get_logger, get_config, save_json, get_timestamp

logger = get_logger(__name__)


class DeveloperProfileBuilder:
    """Builds developer profiles using LLM analysis"""
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        """
        Initialize developer profile builder
        
        Args:
            llm_client: LLM client instance (creates new one if None)
        """
        self.config = get_config()
        self.llm_client = llm_client or LLMClient()
        
        logger.info("✅ Developer Profile Builder initialized")
    
    def build_developer_profile(
        self,
        developer_name: str,
        developer_stats: Dict
    ) -> Optional[Dict]:
        """
        Build AI-generated developer profile
        
        Args:
            developer_name: Developer username
            developer_stats: Statistics about developer's PRs
            
        Returns:
            Developer profile dictionary or None if failed
        """
        logger.info(f"🔨 Building profile for developer: {developer_name}")
        
        try:
            # Build prompt variables
            variables = self._build_profile_variables(developer_name, developer_stats)
            
            # Load template
            template = self.llm_client.load_prompt_template('developer_profile_generation.txt')
            
            # Add format instructions
            variables['format_instructions'] = """
Return ONLY a valid JSON object with no additional text, markdown, or explanation.
Example format:
{
  "developer_name": "username",
  "technical_skills": ["React", "Node.js", "TypeScript"],
  "expertise_areas": ["Frontend", "API Development"],
  "contribution_patterns": ["Bug fixes", "Feature development"],
  "code_quality_focus": ["Testing", "Documentation"],
  "preferred_technologies": ["JavaScript", "Python"],
  "experience_level": "Senior"
}
"""
            
            # Generate profile
            profile_data = self.llm_client.generate(
                template,
                variables,
                parse_json=True
            )
            
            if not profile_data:
                logger.warning(f"⚠️ LLM returned None for {developer_name}")
                return None
            
            # Add metadata
            profile_data['metadata'] = {
                'developer_name': developer_name,
                'profile_url': developer_stats.get('profile_url', ''),
                'avatar_url': developer_stats.get('avatar_url', ''),
                'user_id': developer_stats.get('user_id'),
                'generated_at': get_timestamp(),
                'total_prs_created': developer_stats.get('total_prs_created', 0),
                'total_merged_prs': developer_stats.get('total_merged_prs', 0)
            }
            
            # Add raw stats
            profile_data['statistics'] = developer_stats
            
            logger.info(f"✅ Profile generated for {developer_name}")
            return profile_data
            
        except Exception as e:
            logger.error(f"❌ Failed to build profile for {developer_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def _build_profile_variables(self, developer_name: str, stats: Dict) -> Dict:
        """Build variables for profile generation prompt"""
        
        # PR statistics
        total_prs = stats.get('total_prs_created', 0)
        merged_prs = stats.get('total_merged_prs', 0)
        merge_rate = (merged_prs / total_prs * 100) if total_prs > 0 else 0
        
        # Code change patterns
        avg_additions = stats.get('avg_additions', 0)
        avg_deletions = stats.get('avg_deletions', 0)
        avg_files_changed = stats.get('avg_files_changed', 0)
        
        # PR types and labels
        labels_used = stats.get('labels_used', {})
        top_labels = sorted(labels_used.items(), key=lambda x: x[1], reverse=True)[:5]
        labels_str = ', '.join([f"{label} ({count})" for label, count in top_labels]) if top_labels else 'None'
        
        # PR titles (for pattern analysis)
        pr_titles = stats.get('pr_titles', [])
        titles_sample = '\n'.join([f"  - {title}" for title in pr_titles[:10]])
        
        # Repositories contributed to
        repositories = stats.get('repositories', [])
        repos_str = ', '.join(repositories) if repositories else 'Unknown'
        
        # Time patterns
        activity_by_month = stats.get('activity_by_month', {})
        recent_months = sorted(activity_by_month.items(), reverse=True)[:3]
        activity_str = ', '.join([f"{month}: {count} PRs" for month, count in recent_months]) if recent_months else 'No recent activity'
        
        variables = {
            'developer_name': developer_name,
            'total_prs_created': total_prs,
            'total_merged_prs': merged_prs,
            'merge_rate': f"{merge_rate:.1f}%",
            'avg_additions': int(avg_additions),
            'avg_deletions': int(avg_deletions),
            'avg_files_changed': int(avg_files_changed),
            'common_labels': labels_str,
            'pr_titles_sample': titles_sample if titles_sample else '  (No PR titles available)',
            'repositories_contributed': repos_str,
            'recent_activity': activity_str
        }
        
        return variables
    
    def build_and_save_profile(
        self,
        developer_name: str,
        developer_stats: Dict,
        output_dir: str = "data/profiles/developers"
    ) -> Optional[str]:
        """
        Build and save developer profile to file
        
        Args:
            developer_name: Developer username
            developer_stats: Developer statistics
            output_dir: Output directory for profiles
            
        Returns:
            Path to saved profile file or None if failed
        """
        profile = self.build_developer_profile(developer_name, developer_stats)
        
        if not profile:
            return None
        
        # Save to file
        timestamp = get_timestamp()
        filename = f"{developer_name}_developer_profile_{timestamp}.json"
        filepath = f"{output_dir}/{filename}"
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        save_json(filepath, profile)
        
        logger.info(f"💾 Saved developer profile to {filepath}")
        return filepath


# Example usage
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("🔨 Testing Developer Profile Builder")
    print("=" * 60)
    
    # Sample developer stats
    sample_stats = {
        'username': 'developer1',
        'profile_url': 'https://github.com/developer1',
        'avatar_url': 'https://avatars.githubusercontent.com/u/12345',
        'user_id': 12345,
        'total_prs_created': 45,
        'total_merged_prs': 38,
        'avg_additions': 120,
        'avg_deletions': 45,
        'avg_files_changed': 8,
        'labels_used': {
            'feature': 15,
            'bug': 12,
            'enhancement': 8,
            'documentation': 5
        },
        'pr_titles': [
            'Add user authentication feature',
            'Fix memory leak in data processing',
            'Improve API response time',
            'Update documentation for new endpoints'
        ],
        'repositories': ['owner/repo1', 'owner/repo2'],
        'activity_by_month': {
            '2025-01': 8,
            '2024-12': 12,
            '2024-11': 10
        }
    }
    
    try:
        builder = DeveloperProfileBuilder()
        print("✅ Builder initialized")
        
        print("\n🔨 Building developer profile...")
        profile = builder.build_developer_profile('developer1', sample_stats)
        
        if profile:
            print("\n✅ Developer Profile Generated:")
            print("=" * 60)
            print(f"Developer: {profile['developer_name']}")
            print(f"Experience Level: {profile.get('experience_level', 'Unknown')}")
            print(f"\nTechnical Skills:")
            for skill in profile.get('technical_skills', []):
                print(f"  - {skill}")
            print(f"\nExpertise Areas:")
            for area in profile.get('expertise_areas', []):
                print(f"  - {area}")
            
            print("\n✅ Developer Profile Builder working correctly!")
        else:
            print("❌ Profile generation failed")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
