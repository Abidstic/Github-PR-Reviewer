"""
Reviewer Matcher
Matches best reviewers for PRs using hybrid scoring algorithm
"""

from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from src.profile_generator.profile_storage import ProfileStorage
from src.reviewer_assigner.similarity_matcher import SimilarityMatcher
from src.utils import get_logger, get_config

logger = get_logger(__name__)


class ReviewerMatcher:
    """Matches reviewers to PRs using hybrid scoring"""
    
    def __init__(
        self,
        profile_storage: Optional[ProfileStorage] = None,
        similarity_matcher: Optional[SimilarityMatcher] = None
    ):
        """
        Initialize reviewer matcher
        
        Args:
            profile_storage: ProfileStorage instance (creates new if None)
            similarity_matcher: SimilarityMatcher instance (creates new if None)
        """
        self.config = get_config()
        self.storage = profile_storage or ProfileStorage()
        self.similarity_matcher = similarity_matcher
        
        # Get scoring weights from config
        self.weights = {
            'skill_frequency': self.config.get('reviewer_assignment.weights.skill_frequency', 0.4),
            'experience_level': self.config.get('reviewer_assignment.weights.experience_level', 0.2),
            'review_activity': self.config.get('reviewer_assignment.weights.review_activity', 0.2),
            'similarity_match': self.config.get('reviewer_assignment.weights.similarity_match', 0.2)
        }
        
        # Configuration
        self.top_k = self.config.get('reviewer_assignment.top_k_reviewers', 3)
        self.min_confidence = self.config.get('reviewer_assignment.min_confidence_score', 0.4)
        self.exclude_author = self.config.get('reviewer_assignment.exclude_pr_author', True)
        
        logger.info(f"✅ Reviewer Matcher initialized (weights: {self.weights})")
    
    def match_reviewers(
        self,
        pr_requirements: Dict,
        pr_data: Dict,
        top_k: Optional[int] = None
    ) -> Dict:
        """
        Find best reviewers for PR
        
        Args:
            pr_requirements: From PRAnalyzer.analyze_pr()
            pr_data: Original PR data (must include author info)
            top_k: Number of suggestions (uses config default if None)
        
        Returns:
            {
                "recommended_reviewers": [
                    {
                        "reviewer_name": str,
                        "match_score": float,
                        "reasoning": str,
                        "strengths_alignment": [str],
                        "review_experience": str,
                        "potential_concerns": str
                    }
                ],
                "assignment_confidence": str,  # High/Medium/Low
                "assignment_reasoning": str
            }
        """
        if top_k is None:
            top_k = self.top_k
        
        pr_number = pr_data.get('pr_number', 0)
        pr_author = pr_data.get('author', {}).get('username', 'Unknown') if pr_data.get('author') else 'Unknown'
        
        logger.info(f"🎯 Matching reviewers for PR #{pr_number} (author: {pr_author})")
        
        # Get all reviewers
        all_reviewers = self._get_all_reviewers(exclude_author=pr_author)
        
        if not all_reviewers:
            logger.warning("⚠️ No reviewers available")
            return self._empty_result("No reviewers found in database")
        
        logger.info(f"📊 Evaluating {len(all_reviewers)} reviewers")
        
        # Score all reviewers
        reviewer_scores = []
        
        for reviewer_name, profile in all_reviewers.items():
            score_breakdown = self._score_reviewer(
                reviewer_name,
                profile,
                pr_requirements,
                pr_data
            )
            
            reviewer_scores.append({
                'reviewer_name': reviewer_name,
                'total_score': score_breakdown['total'],
                'breakdown': score_breakdown,
                'profile': profile
            })
        
        # Sort by score
        reviewer_scores.sort(key=lambda x: x['total_score'], reverse=True)
        
        # Filter by minimum confidence
        qualified_reviewers = [
            r for r in reviewer_scores 
            if r['total_score'] >= self.min_confidence
        ]
        
        if not qualified_reviewers:
            logger.warning(f"⚠️ No reviewers met minimum confidence threshold ({self.min_confidence})")
            return self._empty_result(
                f"No reviewers met minimum confidence score of {self.min_confidence}"
            )
        
        # Get top K
        top_reviewers = qualified_reviewers[:top_k]
        
        # Build recommendations
        recommendations = []
        for r in top_reviewers:
            recommendation = self._build_recommendation(
                r['reviewer_name'],
                r['total_score'],
                r['breakdown'],
                r['profile'],
                pr_requirements
            )
            recommendations.append(recommendation)
        
        # Determine overall confidence
        avg_score = sum(r['total_score'] for r in top_reviewers) / len(top_reviewers)
        confidence = self._determine_confidence(avg_score)
        
        # Build reasoning
        reasoning = self._build_assignment_reasoning(
            top_reviewers,
            pr_requirements,
            confidence
        )
        
        # Track assignment
        self._track_assignment(pr_data, recommendations, avg_score)
        
        logger.info(f"✅ Matched {len(recommendations)} reviewers (confidence: {confidence})")
        
        return {
            'recommended_reviewers': recommendations,
            'assignment_confidence': confidence,
            'assignment_reasoning': reasoning
        }
    
    def _get_all_reviewers(self, exclude_author: Optional[str] = None) -> Dict[str, Dict]:
        """
        Get all reviewer profiles
        
        Args:
            exclude_author: Username to exclude (PR author)
        
        Returns:
            Dictionary of {reviewer_name: profile}
        """
        reviewer_names = self.storage.list_reviewers()
        
        profiles = {}
        for name in reviewer_names:
            # CRITICAL: Exclude PR author
            if self.exclude_author and exclude_author:
                if name.lower() == exclude_author.lower():
                    logger.debug(f"🔒 Excluding PR author: {name}")
                    continue
            
            profile = self.storage.get_profile(name)
            if profile:
                profiles[name] = profile
        
        return profiles
    
    def _score_reviewer(
        self,
        reviewer_name: str,
        profile: Dict,
        pr_requirements: Dict,
        pr_data: Dict
    ) -> Dict:
        """
        Score a reviewer using hybrid algorithm
        
        Returns:
            {
                'skill_frequency': float,
                'experience_level': float,
                'review_activity': float,
                'similarity_match': float,
                'total': float
            }
        """
        scores = {
            'skill_frequency': 0.0,
            'experience_level': 0.0,
            'review_activity': 0.0,
            'similarity_match': 0.0
        }
        
        # 1. Skill Frequency Score (40%)
        scores['skill_frequency'] = self._score_skill_frequency(
            profile,
            pr_requirements.get('technical_skills_needed', [])
        )
        
        # 2. Experience Level Score (20%)
        scores['experience_level'] = self._score_experience_level(
            profile,
            pr_requirements.get('complexity_level', 'Medium')
        )
        
        # 3. Review Activity Score (20%)
        scores['review_activity'] = self._score_review_activity(profile)
        
        # 4. Similarity Match Score (20%)
        scores['similarity_match'] = self._score_similarity_match(
            reviewer_name,
            pr_data
        )
        
        # Calculate weighted total
        total = sum(scores[key] * self.weights[key] for key in scores.keys())
        
        scores['total'] = round(total, 3)
        
        return scores
    
    def _score_skill_frequency(self, profile: Dict, required_skills: List[str]) -> float:
        """
        Score based on skill frequency match
        
        Args:
            profile: Reviewer profile
            required_skills: Skills needed for PR
        
        Returns:
            Score between 0.0 and 1.0
        """
        if not required_skills:
            return 0.5  # Neutral score if no skills specified
        
        skill_matrix = profile.get('profile', {}).get('javascript_skill_matrix', {})
        
        # Extract all skills with frequencies
        reviewer_skills = {}
        for category_key, skills in skill_matrix.items():
            for skill in skills:
                if ', frequency:' in skill:
                    parts = skill.split(', frequency:')
                    skill_name = parts[0].strip()
                    try:
                        frequency = int(parts[1].strip())
                        reviewer_skills[skill_name.lower()] = frequency
                    except (ValueError, IndexError):
                        pass
        
        if not reviewer_skills:
            return 0.0
        
        # Find max frequency for normalization
        max_frequency = max(reviewer_skills.values()) if reviewer_skills else 1
        
        # Score each required skill
        skill_scores = []
        for required_skill in required_skills:
            required_skill_lower = required_skill.lower()
            
            # Exact match
            if required_skill_lower in reviewer_skills:
                freq = reviewer_skills[required_skill_lower]
                normalized_score = min(freq / max_frequency, 1.0)
                skill_scores.append(normalized_score)
            # Partial match (e.g., "Express" matches "Express.js")
            else:
                partial_matches = [
                    freq for skill, freq in reviewer_skills.items()
                    if required_skill_lower in skill or skill in required_skill_lower
                ]
                if partial_matches:
                    freq = max(partial_matches)
                    normalized_score = min(freq / max_frequency, 1.0) * 0.8  # Penalty for partial match
                    skill_scores.append(normalized_score)
                else:
                    skill_scores.append(0.0)
        
        # Average score
        if skill_scores:
            return sum(skill_scores) / len(skill_scores)
        else:
            return 0.0
    
    def _score_experience_level(self, profile: Dict, complexity: str) -> float:
        """
        Score based on experience level match
        
        Args:
            profile: Reviewer profile
            complexity: PR complexity (Low/Medium/High)
        
        Returns:
            Score between 0.0 and 1.0
        """
        experience = profile.get('profile', {}).get('experience_level', 'Mid')
        
        # Matching matrix
        match_scores = {
            'Low': {
                'Junior': 1.0,
                'Mid': 0.9,
                'Senior': 0.8,
                'Lead': 0.7
            },
            'Medium': {
                'Junior': 0.6,
                'Mid': 1.0,
                'Senior': 0.9,
                'Lead': 0.8
            },
            'High': {
                'Junior': 0.3,
                'Mid': 0.7,
                'Senior': 1.0,
                'Lead': 1.0
            }
        }
        
        return match_scores.get(complexity, {}).get(experience, 0.5)
    
    def _score_review_activity(self, profile: Dict) -> float:
        """
        Score based on review activity level
        
        Args:
            profile: Reviewer profile
        
        Returns:
            Score between 0.0 and 1.0
        """
        stats = profile.get('stats', {})
        total_reviews = stats.get('total_reviews', 0)
        
        # Normalize (100 reviews = max score)
        score = min(total_reviews / 100.0, 1.0)
        
        return score
    
    def _score_similarity_match(self, reviewer_name: str, pr_data: Dict) -> float:
        """
        Score based on similar PR matches
        
        Args:
            reviewer_name: Reviewer username
            pr_data: PR data
        
        Returns:
            Score between 0.0 and 1.0
        """
        if not self.similarity_matcher or not self.similarity_matcher.vector_store:
            return 0.5  # Neutral score if no similarity data
        
        try:
            # Build query from PR
            query = f"{pr_data.get('title', '')} {pr_data.get('description', '')[:200]}"
            
            # Find similar PRs
            similar_prs = self.similarity_matcher.find_similar_prs(query, k=5)
            
            if not similar_prs:
                return 0.5
            
            # Check if reviewer appears in similar PRs
            reviewer_scores = []
            for doc, similarity_score in similar_prs:
                reviewers = doc.metadata.get('reviewers', [])
                if reviewer_name in reviewers:
                    # Normalize FAISS distance to 0-1 (lower distance = higher similarity)
                    # FAISS returns L2 distance, convert to similarity
                    normalized_similarity = 1.0 / (1.0 + similarity_score)
                    reviewer_scores.append(normalized_similarity)
            
            if reviewer_scores:
                return sum(reviewer_scores) / len(reviewer_scores)
            else:
                return 0.0
                
        except Exception as e:
            logger.warning(f"⚠️ Similarity scoring failed: {e}")
            return 0.5
    
    def _build_recommendation(
        self,
        reviewer_name: str,
        total_score: float,
        score_breakdown: Dict,
        profile: Dict,
        pr_requirements: Dict
    ) -> Dict:
        """Build recommendation dictionary with reasoning"""
        
        # Build reasoning
        reasoning_parts = []
        
        # Skill match reasoning
        skill_score = score_breakdown['skill_frequency']
        if skill_score > 0.7:
            top_skills = self._get_top_skills(profile, pr_requirements.get('technical_skills_needed', []))
            if top_skills:
                reasoning_parts.append(f"High frequency in {', '.join(top_skills)}")
        elif skill_score > 0.4:
            reasoning_parts.append("Moderate skill match")
        
        # Experience reasoning
        exp_score = score_breakdown['experience_level']
        experience = profile.get('profile', {}).get('experience_level', 'Mid')
        complexity = pr_requirements.get('complexity_level', 'Medium')
        if exp_score > 0.8:
            reasoning_parts.append(f"{experience} experience matches {complexity} complexity")
        
        # Activity reasoning
        activity_score = score_breakdown['review_activity']
        total_reviews = profile.get('stats', {}).get('total_reviews', 0)
        if activity_score > 0.5:
            reasoning_parts.append(f"Active reviewer ({total_reviews} reviews)")
        
        # Similarity reasoning
        sim_score = score_breakdown['similarity_match']
        if sim_score > 0.5:
            reasoning_parts.append(f"Reviewed similar PRs")
        
        reasoning = "; ".join(reasoning_parts) if reasoning_parts else "General match"
        
        # Get strengths
        strengths = self._get_matching_strengths(profile, pr_requirements)
        
        # Review experience string
        stats = profile.get('stats', {})
        review_exp = f"{stats.get('total_reviews', 0)} reviews, {stats.get('total_prs', 0)} PRs"
        
        # Potential concerns
        concerns = "None identified"
        if skill_score < 0.3:
            concerns = "Limited skill match"
        elif activity_score < 0.2:
            concerns = "Low review activity"
        
        return {
            'reviewer_name': reviewer_name,
            'match_score': round(total_score, 3),
            'reasoning': reasoning,
            'strengths_alignment': strengths,
            'review_experience': review_exp,
            'potential_concerns': concerns
        }
    
    def _get_top_skills(self, profile: Dict, required_skills: List[str]) -> List[str]:
        """Get top matching skills with frequencies"""
        skill_matrix = profile.get('profile', {}).get('javascript_skill_matrix', {})
        
        matches = []
        for category_key, skills in skill_matrix.items():
            for skill in skills:
                if ', frequency:' in skill:
                    parts = skill.split(', frequency:')
                    skill_name = parts[0].strip()
                    frequency = parts[1].strip()
                    
                    # Check if required
                    for req_skill in required_skills:
                        if req_skill.lower() in skill_name.lower() or skill_name.lower() in req_skill.lower():
                            matches.append(f"{skill_name} ({frequency}x)")
        
        return matches[:3]  # Top 3
    
    def _get_matching_strengths(self, profile: Dict, pr_requirements: Dict) -> List[str]:
        """Get reviewer strengths that match PR requirements"""
        primary_skills = profile.get('profile', {}).get('primary_skills', [])
        required_skills = pr_requirements.get('technical_skills_needed', [])
        
        # Find overlaps
        matches = []
        for skill in primary_skills[:5]:  # Top 5 primary skills
            for req_skill in required_skills:
                if req_skill.lower() in skill.lower() or skill.lower() in req_skill.lower():
                    if skill not in matches:
                        matches.append(skill)
        
        return matches if matches else primary_skills[:3]
    
    def _determine_confidence(self, avg_score: float) -> str:
        """Determine confidence level from average score"""
        if avg_score >= 0.7:
            return "High"
        elif avg_score >= 0.5:
            return "Medium"
        else:
            return "Low"
    
    def _build_assignment_reasoning(
        self,
        top_reviewers: List[Dict],
        pr_requirements: Dict,
        confidence: str
    ) -> str:
        """Build overall assignment reasoning"""
        
        reasoning_parts = []
        
        # Confidence explanation
        if confidence == "High":
            reasoning_parts.append("Strong skill and experience match across suggested reviewers")
        elif confidence == "Medium":
            reasoning_parts.append("Good match found with some trade-offs")
        else:
            reasoning_parts.append("Limited matches available")
        
        # Skill coverage
        required_skills = pr_requirements.get('technical_skills_needed', [])
        if required_skills:
            reasoning_parts.append(f"Covering {len(required_skills)} required skills")
        
        # Experience distribution
        experiences = [r['profile'].get('profile', {}).get('experience_level', 'Mid') for r in top_reviewers]
        unique_exp = set(experiences)
        if len(unique_exp) > 1:
            reasoning_parts.append(f"Diverse experience levels ({', '.join(unique_exp)})")
        
        return ". ".join(reasoning_parts)
    
    def _track_assignment(self, pr_data: Dict, recommendations: List[Dict], confidence_score: float):
        """Track assignment in database"""
        try:
            self.storage.track_assignment(
                pr_number=pr_data.get('pr_number', 0),
                repo_name=pr_data.get('repo_name', 'Unknown'),
                pr_author=pr_data.get('author', {}).get('username', 'Unknown') if pr_data.get('author') else 'Unknown',
                suggested_reviewers=[r['reviewer_name'] for r in recommendations],
                confidence_score=confidence_score
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to track assignment: {e}")
    
    def _empty_result(self, reason: str) -> Dict:
        """Return empty result with reason"""
        return {
            'recommended_reviewers': [],
            'assignment_confidence': 'Low',
            'assignment_reasoning': reason
        }


# Example usage and testing
if __name__ == "__main__":
    print("🎯 Testing Reviewer Matcher")
    print("=" * 60)
    
    # Sample PR requirements (from PRAnalyzer)
    sample_requirements = {
        "technical_skills_needed": ["Node.js", "Express.js", "Jest"],
        "expertise_areas_needed": ["Backend", "Testing"],
        "complexity_level": "Medium",
        "review_focus_areas": ["Code Quality", "Testing Coverage"],
        "primary_language": "JavaScript",
        "frameworks_involved": ["Express.js", "Jest"]
    }
    
    # Sample PR data
    sample_pr_data = {
        'pr_number': 1234,
        'title': 'Fix Express.js routing bug',
        'description': 'Fixed routing issue in Express middleware',
        'author': {'username': 'developer1'},
        'repo_name': 'moment/moment'
    }
    
    try:
        # Initialize matcher
        matcher = ReviewerMatcher()
        print("✅ Matcher initialized")
        
        # Match reviewers
        print("\n🎯 Matching reviewers...")
        result = matcher.match_reviewers(sample_requirements, sample_pr_data)
        
        print(f"\n✅ Assignment Confidence: {result['assignment_confidence']}")
        print(f"📝 Reasoning: {result['assignment_reasoning']}")
        
        print(f"\n👥 Recommended Reviewers ({len(result['recommended_reviewers'])}):")
        print("=" * 60)
        
        for i, rec in enumerate(result['recommended_reviewers'], 1):
            print(f"\n{i}. {rec['reviewer_name']} (Match: {rec['match_score']:.1%})")
            print(f"   💡 {rec['reasoning']}")
            print(f"   ⭐ Strengths: {', '.join(rec['strengths_alignment'])}")
            print(f"   📊 Experience: {rec['review_experience']}")
            if rec['potential_concerns'] != "None identified":
                print(f"   ⚠️  Concerns: {rec['potential_concerns']}")
        
        print("\n✅ Reviewer Matcher working correctly!")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()