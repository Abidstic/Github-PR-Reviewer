"""
Reviewer Matcher
Matches best reviewers for PRs using hybrid scoring algorithm.

Phase 5: reads unified profiles from WindowManager (SQLite) instead of
ProfileStorage.  Developers (is_developer=1) are now candidates too.
"""

import json
import math
from typing import Dict, List, Optional, Tuple

from src.storage.window_manager import WindowManager
from src.reviewer_assigner.similarity_matcher import SimilarityMatcher
from src.utils import get_logger, get_config

logger = get_logger(__name__)


class ReviewerMatcher:
    """Matches reviewers to PRs using hybrid scoring"""

    def __init__(
        self,
        window_manager: Optional[WindowManager] = None,
        similarity_matcher: Optional[SimilarityMatcher] = None
    ):
        self.config = get_config()
        self.window_manager = window_manager or WindowManager()
        self.similarity_matcher = similarity_matcher

        self.weights = {
            'skill_frequency': self.config.get('reviewer_assignment.weights.skill_frequency', 0.4),
            'experience_level': self.config.get('reviewer_assignment.weights.experience_level', 0.2),
            'review_activity': self.config.get('reviewer_assignment.weights.review_activity', 0.2),
            'similarity_match': self.config.get('reviewer_assignment.weights.similarity_match', 0.2)
        }

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
        
        # Get reviewers for this repository
        repo_name = pr_data.get('repo_name')
        all_reviewers = self._get_all_reviewers(repo_name=repo_name, exclude_author=pr_author)
        
        if not all_reviewers:
            logger.warning("⚠️ No reviewers available")
            return self._empty_result("No reviewers found in database")
        
        logger.info(f"📊 Evaluating {len(all_reviewers)} reviewers")

        # Run the FAISS similarity search ONCE per PR. Previously this was
        # re-run (query re-embedded + index re-searched) for every candidate
        # reviewer, i.e. N identical searches per PR.
        similar_prs = self._find_similar_prs_for_pr(pr_data)

        # Score all reviewers
        reviewer_scores = []

        for reviewer_name, profile in all_reviewers.items():
            score_breakdown = self._score_reviewer(
                reviewer_name,
                profile,
                pr_requirements,
                pr_data,
                similar_prs=similar_prs
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
    
    def _get_all_reviewers(
        self,
        repo_name: Optional[str] = None,
        exclude_author: Optional[str] = None
    ) -> Dict[str, Dict]:
        """
        Get candidate profiles (reviewers AND developers) for a repo.

        Returns:
            Dictionary of {username: profile_row_dict}
        """
        if not repo_name:
            return {}

        all_users = self.window_manager.get_all_users(
            repo_name, include_developers=True
        )

        profiles = {}
        for user_row in all_users:
            username = user_row['username']

            if self.exclude_author and exclude_author:
                if username.lower() == exclude_author.lower():
                    logger.debug(f"🔒 Excluding PR author: {username}")
                    continue

            profiles[username] = user_row

        return profiles
    
    def _find_similar_prs_for_pr(self, pr_data: Dict) -> Optional[List[Tuple]]:
        """
        Run the vector similarity search once for this PR.

        Returns:
            List of (Document, distance) tuples, or None when no vector store
            is available (scorers then fall back to a neutral 0.5).
        """
        if not self.similarity_matcher or not self.similarity_matcher.vector_store:
            return None

        try:
            # 'or' guards against description being None (PRs with empty body)
            query = f"{pr_data.get('title') or ''} {(pr_data.get('description') or '')[:200]}"
            k = self.config.get('reviewer_assignment.top_k_similar_prs', 5)
            return self.similarity_matcher.find_similar_prs(query, k=k)
        except Exception as e:
            logger.warning(f"⚠️ Similarity search failed: {e}")
            return None

    def _score_reviewer(
        self,
        reviewer_name: str,
        profile: Dict,
        pr_requirements: Dict,
        pr_data: Dict,
        similar_prs: Optional[List[Tuple]] = None
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
        
        # 4. Similarity Match Score (20%) — uses the pre-computed per-PR search
        scores['similarity_match'] = self._score_similarity_match(
            reviewer_name,
            similar_prs
        )

        # 5. Repository Membership Bonus
        # In the per-repo model all candidates belong to this repo, so
        # the bonus applies universally.  Kept for scoring parity.
        repo_bonus = 0.5
        
        # Calculate weighted total
        total = sum(scores[key] * self.weights[key] for key in scores.keys())
        
        # Add the repo bonus (capped at 1.0 total)
        total = min(total + repo_bonus, 1.0)
        
        scores['total'] = round(total, 3)
        
        return scores
    
    @staticmethod
    def _parse_skill_matrix(profile: Dict) -> Dict:
        """Parse javascript_skill_matrix from a profile row (JSON string or dict)."""
        raw = profile.get('javascript_skill_matrix')
        if not raw:
            return {}
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        return raw

    def _score_skill_frequency(self, profile: Dict, required_skills: List[str]) -> float:
        """Score based on skill frequency match (0.0–1.0)."""
        if not required_skills:
            return 0.5

        skill_matrix = self._parse_skill_matrix(profile)

        reviewer_skills: Dict[str, int] = {}
        for _category_key, skills in skill_matrix.items():
            if not isinstance(skills, list):
                continue
            for skill in skills:
                if ', frequency:' in str(skill):
                    parts = str(skill).split(', frequency:')
                    skill_name = parts[0].strip()
                    try:
                        frequency = int(parts[1].strip())
                        reviewer_skills[skill_name.lower()] = frequency
                    except (ValueError, IndexError):
                        pass

        if not reviewer_skills:
            return 0.0

        max_frequency = max(reviewer_skills.values())

        skill_scores = []
        for required_skill in required_skills:
            req_lower = required_skill.lower()

            if req_lower in reviewer_skills:
                freq = reviewer_skills[req_lower]
                skill_scores.append(min(freq / max_frequency, 1.0))
            else:
                partial_matches = [
                    freq for skill, freq in reviewer_skills.items()
                    if req_lower in skill or skill in req_lower
                ]
                if partial_matches:
                    freq = max(partial_matches)
                    skill_scores.append(min(freq / max_frequency, 1.0) * 0.8)
                else:
                    skill_scores.append(0.0)

        return sum(skill_scores) / len(skill_scores) if skill_scores else 0.0
    
    def _score_experience_level(self, profile: Dict, complexity: str) -> float:
        """Score based on experience level match (0.0–1.0)."""
        experience = profile.get('experience_level') or 'Mid'
        
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
        """Score based on review activity level (0.0–1.0)."""
        total_reviews = profile.get('total_reviews', 0)
        return min(math.sqrt(total_reviews / 10.0), 1.0)
    
    def _score_similarity_match(
        self,
        reviewer_name: str,
        similar_prs: Optional[List[Tuple]]
    ) -> float:
        """
        Score based on similar PR matches.

        The similarity search itself is executed ONCE per PR in
        match_reviewers() (_find_similar_prs_for_pr) and the results are
        shared across all candidate reviewers.

        Args:
            reviewer_name: Reviewer username
            similar_prs: Pre-computed list of (Document, L2 distance) tuples,
                         or None when no vector store / search failed

        Returns:
            Score between 0.0 and 1.0
        """
        if similar_prs is None or not similar_prs:
            return 0.5  # Neutral score if no similarity data

        try:
            # Check if reviewer appears in similar PRs
            reviewer_scores = []
            for doc, distance in similar_prs:
                reviewers = doc.metadata.get('reviewers', [])
                if reviewer_name in reviewers:
                    # Normalize FAISS distance to 0-1 (lower distance = higher similarity)
                    # FAISS returns L2 distance, convert to similarity
                    normalized_similarity = 1.0 / (1.0 + distance)
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
        """Build recommendation dictionary with reasoning."""
        reasoning_parts = []

        skill_score = score_breakdown['skill_frequency']
        if skill_score > 0.7:
            top_skills = self._get_top_skills(profile, pr_requirements.get('technical_skills_needed', []))
            if top_skills:
                reasoning_parts.append(f"High frequency in {', '.join(top_skills)}")
        elif skill_score > 0.4:
            reasoning_parts.append("Moderate skill match")

        exp_score = score_breakdown['experience_level']
        experience = profile.get('experience_level') or 'Mid'
        complexity = pr_requirements.get('complexity_level', 'Medium')
        if exp_score > 0.8:
            reasoning_parts.append(f"{experience} experience matches {complexity} complexity")

        activity_score = score_breakdown['review_activity']
        total_reviews = profile.get('total_reviews', 0)
        if activity_score > 0.5:
            reasoning_parts.append(f"Active reviewer ({total_reviews} reviews)")

        sim_score = score_breakdown['similarity_match']
        if sim_score > 0.5:
            reasoning_parts.append("Reviewed similar PRs")

        reasoning = "; ".join(reasoning_parts) if reasoning_parts else "General match"

        strengths = self._get_matching_strengths(profile, pr_requirements)

        total_authored = profile.get('total_prs_authored', 0)
        review_exp = f"{total_reviews} reviews, {total_authored} PRs authored"

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
        """Get top matching skills with frequencies."""
        skill_matrix = self._parse_skill_matrix(profile)

        matches = []
        for _category_key, skills in skill_matrix.items():
            if not isinstance(skills, list):
                continue
            for skill in skills:
                if ', frequency:' in str(skill):
                    parts = str(skill).split(', frequency:')
                    skill_name = parts[0].strip()
                    frequency = parts[1].strip()
                    for req_skill in required_skills:
                        if req_skill.lower() in skill_name.lower() or skill_name.lower() in req_skill.lower():
                            matches.append(f"{skill_name} ({frequency}x)")

        return matches[:3]
    
    @staticmethod
    def _parse_json_field(profile: Dict, key: str) -> list:
        """Parse a JSON-encoded list field from a profile row."""
        raw = profile.get(key)
        if not raw:
            return []
        if isinstance(raw, list):
            return raw
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    def _get_matching_strengths(self, profile: Dict, pr_requirements: Dict) -> List[str]:
        """Get reviewer strengths that match PR requirements."""
        primary_skills = self._parse_json_field(profile, 'primary_skills')
        required_skills = pr_requirements.get('technical_skills_needed', [])

        matches = []
        for skill in primary_skills[:5]:
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
        experiences = [r['profile'].get('experience_level') or 'Mid' for r in top_reviewers]
        unique_exp = set(experiences)
        if len(unique_exp) > 1:
            reasoning_parts.append(f"Diverse experience levels ({', '.join(unique_exp)})")
        
        return ". ".join(reasoning_parts)
    
    def _track_assignment(self, pr_data: Dict, recommendations: List[Dict], confidence_score: float):
        """Track assignment in database."""
        try:
            pr_author = 'Unknown'
            if pr_data.get('author'):
                pr_author = pr_data['author'].get('username', 'Unknown')
            self.window_manager.track_assignment(
                pr_number=pr_data.get('pr_number', 0),
                repo_name=pr_data.get('repo_name', 'Unknown'),
                pr_author=pr_author,
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

    sample_requirements = {
        "technical_skills_needed": ["Node.js", "Express.js", "Jest"],
        "expertise_areas_needed": ["Backend", "Testing"],
        "complexity_level": "Medium",
        "review_focus_areas": ["Code Quality", "Testing Coverage"],
        "primary_language": "JavaScript",
        "frameworks_involved": ["Express.js", "Jest"]
    }

    sample_pr_data = {
        'pr_number': 1234,
        'title': 'Fix Express.js routing bug',
        'description': 'Fixed routing issue in Express middleware',
        'author': {'username': 'developer1'},
        'repo_name': 'moment/moment'
    }

    try:
        matcher = ReviewerMatcher()
        result = matcher.match_reviewers(sample_requirements, sample_pr_data)

        print(f"Assignment Confidence: {result['assignment_confidence']}")
        print(f"Reviewers: {len(result['recommended_reviewers'])}")
        for i, rec in enumerate(result['recommended_reviewers'], 1):
            print(f"  {i}. {rec['reviewer_name']} ({rec['match_score']:.1%})")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()