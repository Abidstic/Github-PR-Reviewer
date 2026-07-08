"""
Suggestion Formatter
Formats reviewer recommendations as GitHub markdown comments
"""

from typing import Dict, List
from datetime import datetime

from src.utils import get_logger

logger = get_logger(__name__)


class SuggestionFormatter:
    """Formats reviewer suggestions for GitHub comments"""
    
    def __init__(self):
        """Initialize formatter"""
        logger.info("✅ Suggestion Formatter initialized")
    
    def format_as_markdown(
        self,
        recommendations: Dict,
        pr_data: Dict,
        pr_requirements: Dict
    ) -> str:
        """
        Format recommendations as GitHub markdown comment
        
        Args:
            recommendations: From ReviewerMatcher.match_reviewers()
            pr_data: Original PR data
            pr_requirements: From PRAnalyzer.analyze_pr()
        
        Returns:
            Formatted markdown string
        """
        pr_number = pr_data.get('pr_number', 0)
        pr_author = pr_data.get('author', {}).get('username', 'Unknown') if pr_data.get('author') else 'Unknown'

        # On FORK repos, profiles come from the parent repo's reviewers.
        # @-mentioning them would send GitHub notifications to real people who
        # have no relation to this fork, so render names as plain code instead.
        is_fork = pr_data.get('is_fork', False)
        mention = (lambda u: f"`{u}`") if is_fork else (lambda u: f"@{u}")

        logger.info(f"📝 Formatting suggestions for PR #{pr_number} (fork={is_fork})")

        # Build markdown
        lines = []

        # Header
        lines.append("## 🤖 AI-Powered Reviewer Suggestions")
        lines.append("")
        lines.append(f"**Pull Request:** #{pr_number} - {pr_data.get('title', 'Untitled')}")
        lines.append(f"**Author:** {mention(pr_author)}")
        lines.append(f"**Complexity:** {pr_requirements.get('complexity_level', 'Unknown')}")
        lines.append("")
        
        # Assignment confidence
        confidence = recommendations.get('assignment_confidence', 'Unknown')
        confidence_emoji = {
            'High': '🟢',
            'Medium': '🟡',
            'Low': '🔴'
        }.get(confidence, '⚪')
        
        lines.append(f"**Assignment Confidence:** {confidence_emoji} {confidence}")
        lines.append(f"_{recommendations.get('assignment_reasoning', '')}_")
        lines.append("")
        
        # Recommended reviewers
        reviewers = recommendations.get('recommended_reviewers', [])
        
        if not reviewers:
            lines.append("### ⚠️ No Suitable Reviewers Found")
            lines.append("")
            lines.append("The AI system could not identify suitable reviewers for this PR.")
            lines.append("Please manually assign reviewers based on team knowledge.")
        else:
            lines.append(f"### 👥 Recommended Reviewers ({len(reviewers)})")
            lines.append("")
            
            for i, reviewer in enumerate(reviewers, 1):
                lines.append(f"#### {i}. {mention(reviewer['reviewer_name'])} "
                           f"({self._format_percentage(reviewer['match_score'])} match)")
                lines.append("")
                
                # Reasoning
                lines.append(f"**💡 Why this reviewer?**")
                lines.append(f"- {reviewer['reasoning']}")
                lines.append("")
                
                # Strengths
                if reviewer.get('strengths_alignment'):
                    strengths = reviewer['strengths_alignment'][:3]  # Top 3
                    lines.append(f"**⭐ Relevant Strengths:** {', '.join(strengths)}")
                    lines.append("")
                
                # Experience
                lines.append(f"**📊 Review Experience:** {reviewer['review_experience']}")
                lines.append("")
                
                # Concerns (if any)
                if reviewer.get('potential_concerns') and reviewer['potential_concerns'] != "None identified":
                    lines.append(f"**⚠️ Note:** {reviewer['potential_concerns']}")
                    lines.append("")
        
        # Technical requirements
        lines.append("---")
        lines.append("")
        lines.append("### 📋 PR Requirements Analysis")
        lines.append("")
        
        # Skills needed
        skills = pr_requirements.get('technical_skills_needed', [])
        if skills:
            lines.append(f"**Technical Skills:** {', '.join(skills[:5])}")
            if len(skills) > 5:
                lines.append(f"_... and {len(skills) - 5} more_")
            lines.append("")
        
        # Expertise areas
        expertise = pr_requirements.get('expertise_areas_needed', [])
        if expertise:
            lines.append(f"**Expertise Areas:** {', '.join(expertise)}")
            lines.append("")
        
        # Review focus
        focus = pr_requirements.get('review_focus_areas', [])
        if focus:
            lines.append(f"**Review Focus:** {', '.join(focus)}")
            lines.append("")
        
        # Footer
        lines.append("---")
        lines.append("")
        lines.append("_🤖 This suggestion was generated by GitHub Reviewer AI_")
        lines.append(f"_Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}_")
        lines.append("")
        lines.append("**Note:** These are AI-generated suggestions based on historical review patterns. "
                    "Please use your judgment and team knowledge when making final reviewer assignments.")
        
        markdown = "\n".join(lines)
        
        logger.debug(f"✅ Formatted {len(lines)} lines of markdown")
        return markdown
    
    def format_as_compact_markdown(
        self,
        recommendations: Dict,
        pr_data: Dict
    ) -> str:
        """
        Format as compact markdown (for smaller comments)
        
        Args:
            recommendations: From ReviewerMatcher.match_reviewers()
            pr_data: Original PR data
        
        Returns:
            Compact markdown string
        """
        pr_number = pr_data.get('pr_number', 0)
        
        lines = []
        lines.append("## 🤖 Suggested Reviewers")
        lines.append("")
        
        confidence = recommendations.get('assignment_confidence', 'Unknown')
        confidence_emoji = {'High': '🟢', 'Medium': '🟡', 'Low': '🔴'}.get(confidence, '⚪')
        
        reviewers = recommendations.get('recommended_reviewers', [])
        
        if not reviewers:
            lines.append("⚠️ No suitable reviewers found.")
        else:
            mention = (lambda u: f"`{u}`") if pr_data.get('is_fork', False) else (lambda u: f"@{u}")
            for i, reviewer in enumerate(reviewers, 1):
                score_str = self._format_percentage(reviewer['match_score'])
                lines.append(f"{i}. **{mention(reviewer['reviewer_name'])}** ({score_str}) - {reviewer['reasoning']}")
        
        lines.append("")
        lines.append(f"_Confidence: {confidence_emoji} {confidence}_")
        
        return "\n".join(lines)
    
    def format_as_plain_text(
        self,
        recommendations: Dict,
        pr_data: Dict
    ) -> str:
        """
        Format as plain text (for terminal output)
        
        Args:
            recommendations: From ReviewerMatcher.match_reviewers()
            pr_data: Original PR data
        
        Returns:
            Plain text string
        """
        pr_number = pr_data.get('pr_number', 0)
        pr_title = pr_data.get('title', 'Untitled')
        
        lines = []
        lines.append("=" * 70)
        lines.append(f"🎯 SUGGESTED REVIEWERS FOR PR #{pr_number}")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"Title: {pr_title}")
        lines.append(f"Confidence: {recommendations.get('assignment_confidence', 'Unknown')}")
        lines.append(f"Reasoning: {recommendations.get('assignment_reasoning', '')}")
        lines.append("")
        
        reviewers = recommendations.get('recommended_reviewers', [])
        
        if not reviewers:
            lines.append("⚠️  No suitable reviewers found.")
        else:
            lines.append(f"Recommended Reviewers ({len(reviewers)}):")
            lines.append("-" * 70)
            
            for i, reviewer in enumerate(reviewers, 1):
                lines.append("")
                lines.append(f"{i}. {reviewer['reviewer_name']} "
                           f"(Match: {self._format_percentage(reviewer['match_score'])})")
                lines.append(f"   💡 {reviewer['reasoning']}")
                
                if reviewer.get('strengths_alignment'):
                    strengths = ', '.join(reviewer['strengths_alignment'][:3])
                    lines.append(f"   ⭐ Strengths: {strengths}")
                
                lines.append(f"   📊 Experience: {reviewer['review_experience']}")
        
        lines.append("")
        lines.append("=" * 70)
        
        return "\n".join(lines)
    
    def _format_percentage(self, score: float) -> str:
        """Format score as percentage"""
        return f"{int(score * 100)}%"


# Example usage and testing
if __name__ == "__main__":
    print("📝 Testing Suggestion Formatter")
    print("=" * 60)
    
    # Sample data
    sample_recommendations = {
        'recommended_reviewers': [
            {
                'reviewer_name': 'reviewer1',
                'match_score': 0.85,
                'reasoning': 'High frequency in Express.js (10x), Node.js (8x); Senior experience matches High complexity; Active reviewer (45 reviews)',
                'strengths_alignment': ['Express.js', 'Node.js', 'Backend'],
                'review_experience': '45 reviews, 12 PRs',
                'potential_concerns': 'None identified'
            },
            {
                'reviewer_name': 'reviewer2',
                'match_score': 0.72,
                'reasoning': 'Strong in Backend Development (15x); Mid-level, very active (65 reviews)',
                'strengths_alignment': ['Backend', 'API Design', 'Testing'],
                'review_experience': '65 reviews, 20 PRs',
                'potential_concerns': 'None identified'
            },
            {
                'reviewer_name': 'reviewer3',
                'match_score': 0.68,
                'reasoning': 'Testing expertise (Jest 8x, Mocha 5x); Senior, thorough reviewer',
                'strengths_alignment': ['Jest', 'Testing', 'Code Quality'],
                'review_experience': '38 reviews, 15 PRs',
                'potential_concerns': 'Limited backend experience'
            }
        ],
        'assignment_confidence': 'High',
        'assignment_reasoning': 'Strong skill and experience match across suggested reviewers. Covering 3 required skills. Diverse experience levels (Senior, Mid)'
    }
    
    sample_pr = {
        'pr_number': 1234,
        'title': 'Fix Express.js routing bug in API endpoints',
        'author': {'username': 'developer1'},
        'repo_name': 'moment/moment'
    }
    
    sample_requirements = {
        'technical_skills_needed': ['Node.js', 'Express.js', 'Jest'],
        'expertise_areas_needed': ['Backend', 'Testing'],
        'complexity_level': 'Medium',
        'review_focus_areas': ['Code Quality', 'Testing Coverage'],
        'primary_language': 'JavaScript',
        'frameworks_involved': ['Express.js', 'Jest']
    }
    
    # Initialize formatter
    formatter = SuggestionFormatter()
    
    # Test markdown formatting
    print("\n📄 Full Markdown Format:")
    print("-" * 60)
    markdown = formatter.format_as_markdown(
        sample_recommendations,
        sample_pr,
        sample_requirements
    )
    print(markdown)
    
    # Test compact format
    print("\n📄 Compact Format:")
    print("-" * 60)
    compact = formatter.format_as_compact_markdown(
        sample_recommendations,
        sample_pr
    )
    print(compact)
    
    # Test plain text
    print("\n📄 Plain Text Format:")
    print("-" * 60)
    plain = formatter.format_as_plain_text(
        sample_recommendations,
        sample_pr
    )
    print(plain)
    
    print("\n✅ Suggestion Formatter working correctly!")