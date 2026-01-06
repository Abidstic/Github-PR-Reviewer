"""
Reviewer Profile Builder
Generates reviewer profiles using LLM analysis
"""

import json
import time
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from src.profile_generator.llm_client import LLMClient
from src.profile_generator.prompt_builder import PromptBuilder
from src.profile_generator.skill_analyzer import SkillAnalyzer
from src.utils import get_logger, get_config, save_json, get_timestamp

logger = get_logger(__name__)


class ReviewerProfile(BaseModel):
    """Pydantic model for reviewer profile"""
    reviewer_name: str = Field(description="Reviewer's username")
    experience_level: str = Field(description="Estimated experience level (Junior/Mid/Senior/Lead)")
    primary_skills: List[str] = Field(description="List of primary JavaScript technical skills")
    programming_languages: List[str] = Field(description="Programming languages expertise")
    summary: str = Field(description="Overall JavaScript reviewer profile summary")
    javascript_skill_matrix: Dict[str, List[str]] = Field(
        description="Detailed JavaScript skill assessment with frequency"
    )


class ReviewerProfileBuilder:
    """Builds reviewer profiles using AI analysis"""
    
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        output_dir: str = "data/profiles/reviewers"
    ):
        """
        Initialize reviewer profile builder
        
        Args:
            llm_client: LLMClient instance (creates new one if None)
            output_dir: Directory to save profile JSON files
        """
        self.llm = llm_client or LLMClient()
        self.prompt_builder = PromptBuilder()
        self.skill_analyzer = SkillAnalyzer()
        self.config = get_config()
        self.output_dir = Path(output_dir)
        
        # Settings from config
        self.min_reviews = self.config.get('profile_generation.min_reviews_for_profile', 2)
        self.max_reviews_for_analysis = 20  # Limit to avoid token overflow
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"✅ Reviewer profile builder initialized (output: {self.output_dir})")
    
    def prepare_review_data(self, reviewer_data: Dict) -> List[Dict]:
        """
        Prepare review data for analysis
        
        Args:
            reviewer_data: Reviewer statistics and review details
        
        Returns:
            Summarized review data list
        """
        review_details = reviewer_data.get('review_details', [])
        
        # Limit to max reviews
        limited_reviews = review_details[:self.max_reviews_for_analysis]
        
        review_summary = []
        for review in limited_reviews:
            summary = {
                'pr_title': review.get('title', '')[:100],
                'repo': review.get('repo', ''),
                'labels': review.get('labels', []),
                'review_state': review.get('review_state', ''),
                'additions': review.get('additions', 0),
                'deletions': review.get('deletions', 0),
                'files_changed': review.get('changed_files_count', 0)
            }
            
            # Add description if available and short
            if review.get('description') and len(review.get('description', '')) < 500:
                summary['pr_description'] = review['description'][:300]
            
            # Add review body if available and short
            if review.get('review_body') and len(review.get('review_body', '')) < 500:
                summary['review_comment'] = review['review_body'][:300]
            
            review_summary.append(summary)
        
        return review_summary
    
    def analyze_skills(self, reviewer_name: str, review_data: List[Dict]) -> str:
        """
        Analyze reviewer skills using LLM
        
        Args:
            reviewer_name: Reviewer username
            review_data: Prepared review data
        
        Returns:
            Skills analysis text from LLM
        """
        logger.info(f"🔍 Analyzing skills for {reviewer_name}...")
        
        # Build prompt variables
        variables = self.prompt_builder.build_skills_analysis_variables(
            reviewer_name,
            review_data
        )
        
        # Load skills analysis template
        template = self.llm.load_prompt_template('reviewer_skills_analysis.txt')
        
        # Generate analysis
        skills_analysis = self.llm.generate(template, variables)
        
        logger.info(f"✅ Skills analysis complete for {reviewer_name}")
        return skills_analysis
    
    def generate_profile(
        self,
        reviewer_name: str,
        skills_analysis: str,
        reviewer_stats: Dict
    ) -> Optional[Dict]:
        """
        Generate reviewer profile from skills analysis
        
        Args:
            reviewer_name: Reviewer username
            skills_analysis: Skills analysis from LLM
            reviewer_stats: Reviewer statistics
        
        Returns:
            Generated profile dictionary or None on failure
        """
        logger.info(f"🤖 Generating profile for {reviewer_name}...")
        
        # Get Pydantic format instructions
        from langchain.output_parsers import PydanticOutputParser
        parser = PydanticOutputParser(pydantic_object=ReviewerProfile)
        format_instructions = parser.get_format_instructions()
        
        # Build prompt variables
        repo_list = ', '.join(reviewer_stats.get('repos', []))
        variables = self.prompt_builder.build_profile_generation_variables(
            reviewer_name=reviewer_name,
            skills_analysis=skills_analysis,
            review_count=reviewer_stats.get('total_reviews', 0),
            repo_list=repo_list,
            format_instructions=format_instructions
        )
        
        # Load profile generation template
        template = self.llm.load_prompt_template('reviewer_profile_generation.txt')
        
        try:
            # Generate profile
            profile_result = self.llm.generate(template, variables, parse_json=True)
            
            # Validate as Pydantic model
            profile = ReviewerProfile(**profile_result)
            profile_dict = profile.dict()
            
            # Validate and fix skill matrix
            is_valid, errors = self.skill_analyzer.validate_skill_matrix(
                profile_dict['javascript_skill_matrix']
            )
            
            if not is_valid:
                logger.warning(f"⚠️ Profile validation failed for {reviewer_name}, attempting auto-fix...")
                logger.debug(f"Errors: {errors}")
                
                # Attempt to fix
                fixed_matrix = self.skill_analyzer.fix_skill_matrix(
                    profile_dict['javascript_skill_matrix']
                )
                profile_dict['javascript_skill_matrix'] = fixed_matrix
                
                # Re-validate
                is_valid, errors = self.skill_analyzer.validate_skill_matrix(fixed_matrix)
                if not is_valid:
                    logger.error(f"❌ Could not fix profile for {reviewer_name}")
                    logger.debug(f"Remaining errors: {errors}")
                else:
                    logger.info(f"✅ Profile auto-fixed for {reviewer_name}")
            
            # Extract primary skills if not provided or incorrect
            if not profile_dict.get('primary_skills') or len(profile_dict['primary_skills']) == 0:
                primary_skills = self.skill_analyzer.extract_primary_skills(
                    profile_dict['javascript_skill_matrix'],
                    min_frequency=3
                )
                profile_dict['primary_skills'] = primary_skills[:5]  # Top 5
            
            logger.info(f"✅ Profile generated for {reviewer_name}")
            return profile_dict
            
        except Exception as e:
            logger.error(f"❌ Failed to generate profile for {reviewer_name}: {e}")
            return None
    
    def build_reviewer_profile(
        self,
        reviewer_name: str,
        reviewer_stats: Dict
    ) -> Optional[Dict]:
        """
        Complete workflow: analyze skills + generate profile
        
        Args:
            reviewer_name: Reviewer username
            reviewer_stats: Reviewer statistics with review details
        
        Returns:
            Complete profile data or None on failure
        """
        # Check minimum review threshold
        total_reviews = reviewer_stats.get('total_reviews', 0)
        if total_reviews < self.min_reviews:
            logger.warning(
                f"⚠️ {reviewer_name} has only {total_reviews} reviews "
                f"(min: {self.min_reviews}). Skipping."
            )
            return None
        
        logger.info(f"📋 Building profile for {reviewer_name} ({total_reviews} reviews)")
        
        # Step 1: Prepare review data
        review_data = self.prepare_review_data(reviewer_stats)
        
        if not review_data:
            logger.warning(f"⚠️ No review data available for {reviewer_name}")
            return None
        
        # Step 2: Analyze skills
        skills_analysis = self.analyze_skills(reviewer_name, review_data)
        
        # Step 3: Generate profile
        profile = self.generate_profile(reviewer_name, skills_analysis, reviewer_stats)
        
        if not profile:
            return None
        
        # Step 4: Package complete profile data
        timestamp = get_timestamp()
        profile_data = {
            "reviewer_name": reviewer_name,
            "generated_at": timestamp,
            "stats": {
                'total_reviews': reviewer_stats.get('total_reviews', 0),
                'total_comments': reviewer_stats.get('total_comments', 0),
                'total_prs': reviewer_stats.get('total_prs', 0),
                'repos': reviewer_stats.get('repos', [])
            },
            "profile": profile
        }
        
        return profile_data
    
    def save_profile(self, profile_data: Dict) -> str:
        """
        Save profile to JSON file
        
        Args:
            profile_data: Complete profile data
        
        Returns:
            Path to saved file
        """
        reviewer_name = profile_data['reviewer_name']
        timestamp = profile_data['generated_at']
        
        filename = f"{reviewer_name}_reviewer_profile_{timestamp}.json"
        filepath = self.output_dir / filename
        
        save_json(str(filepath), profile_data)
        logger.info(f"💾 Saved profile: {filepath}")
        
        return str(filepath)
    
    def build_and_save_profile(
        self,
        reviewer_name: str,
        reviewer_stats: Dict
    ) -> Optional[str]:
        """
        Build profile and save to file
        
        Args:
            reviewer_name: Reviewer username
            reviewer_stats: Reviewer statistics
        
        Returns:
            Path to saved file or None on failure
        """
        profile_data = self.build_reviewer_profile(reviewer_name, reviewer_stats)
        
        if profile_data:
            return self.save_profile(profile_data)
        
        return None


# Example usage and testing
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    print("🏗️ Testing Reviewer Profile Builder")
    print("=" * 60)
    
    # Initialize builder
    builder = ReviewerProfileBuilder(output_dir="data/profiles/reviewers")
    
    # Sample reviewer data
    sample_reviewer = {
        'total_reviews': 5,
        'total_comments': 3,
        'total_prs': 4,
        'repos': ['moment'],
        'review_details': [
            {
                'title': 'Fix Express.js routing bug',
                'repo': 'moment',
                'review_state': 'APPROVED',
                'labels': ['bug', 'backend'],
                'additions': 50,
                'deletions': 10,
                'changed_files_count': 3
            },
            {
                'title': 'Add moment.js locale support',
                'repo': 'moment',
                'review_state': 'CHANGES_REQUESTED',
                'labels': ['enhancement'],
                'additions': 100,
                'deletions': 20,
                'changed_files_count': 5
            }
        ]
    }
    
    # Build profile
    print("\n🔄 Building test profile...")
    filepath = builder.build_and_save_profile('test_reviewer', sample_reviewer)
    
    if filepath:
        print(f"✅ Profile saved to: {filepath}")
    else:
        print("❌ Failed to build profile")
    
    print("\n✅ Reviewer profile builder working correctly!")