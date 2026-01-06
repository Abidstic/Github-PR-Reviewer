# src/profile_generator/skill_analyzer.py
"""
Skill Analyzer
Validates and processes JavaScript skills from LLM responses
"""

import re
from typing import Dict, List, Set, Tuple, Optional

from src.utils import get_logger, get_config

logger = get_logger(__name__)


class SkillAnalyzer:
    """Analyzes and validates JavaScript skills"""
    
    def __init__(self):
        """Initialize skill analyzer"""
        self.config = get_config()
        
        # Valid JavaScript skill categories
        self.valid_categories = self.config.get('profile_generation.skill_categories', [])
        
        # Valid skills for each category (from your notebooks)
        self.valid_skills = {
            "Framework/Library Expertise": {
                "React", "Angular", "Vue.js", "Svelte", "Ember.js", "Backbone.js",
                "Mithril", "Preact", "jQuery", "moment.js", "moment",
                "Node.js", "Express.js", "Koa.js",
                "Redux", "Context API", "Zustand",
                "Jest", "Mocha", "Chai",
                "Next.js", "Nuxt.js"
            },
            "Asynchronous Programming": {
                "async/await", "Promises", "Callbacks", "Event Loop", "Concurrency Control"
            },
            "API Design & Consumption": {
                "RESTful APIs", "GraphQL", "WebSockets",
                "Authentication & Authorization", "API Error Handling", "Rate Limiting"
            },
            "Error Handling": {
                "Try-Catch", "Custom Error Classes", "Error Boundaries"
            },
            "Frontend Development Skills": {
                "DOM Manipulation"
            },
            "Backend Development Skills": {
                "Server-Side Logic", "Database Integration", "API Endpoints",
                "Authentication/Authorization", "Middleware", "Microservices", "Caching"
            },
            "DevOps & Deployment": {
                "CI/CD Pipelines", "Containerization", "Cloud Providers",
                "Load Balancing", "Web Servers"
            },
            "Advanced JavaScript Concepts": {
                "Closures", "Higher-Order Functions", "Prototypes & Inheritance",
                "Module Systems", "Event Delegation", "Memory Management"
            },
            "Functional Programming": {
                "Immutability", "Pure Functions", "Declarative Programming", "Composition"
            },
            "Data Structures & Algorithms": {
                "Data Structures", "Searching and Sorting Algorithms", "Recursion", "Big O Notation"
            },
            "TypeScript": {
                "Type Definitions", "Generics", "Type Inference",
                "Modules & Namespaces", "Type Narrowing"
            },
            "Progressive Web Apps (PWA)": {
                "Service Workers", "Web Push Notifications", "Caching Strategies",
                "App Shell Model", "Manifest File"
            },
            "Mobile Development with JavaScript": {
                "React Native", "Ionic", "Cordova/PhoneGap"
            },
            "Web Performance Optimization": {
                "Lazy Loading", "Code Splitting", "Minification & Compression",
                "Critical Rendering Path Optimization", "Preloading & Prefetching"
            },
            "Event-Driven Architecture": {
                "Event Emitters", "Pub/Sub Model"
            },
            "Dependency Management": {
                "npm/yarn", "Package-lock.json & Yarn.lock"
            },
            "Graphical Data Visualization": {
                "D3.js", "Chart.js", "WebGL & Three.js"
            }
        }
        
        logger.info("✅ Skill analyzer initialized")
    
    def validate_skill_matrix(self, skill_matrix: Dict[str, List[str]]) -> Tuple[bool, List[str]]:
        """
        Validate JavaScript skill matrix from LLM
        
        Args:
            skill_matrix: Skill matrix dictionary from LLM
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        if not skill_matrix:
            errors.append("Skill matrix is empty")
            return False, errors
        
        # Check if all valid categories are present
        matrix_categories = set()
        for key in skill_matrix.keys():
            # Extract base category name (remove frequency)
            base_category = key.split(', frequency:')[0].strip()
            matrix_categories.add(base_category)
        
        missing_categories = set(self.valid_categories) - matrix_categories
        if missing_categories:
            errors.append(f"Missing categories: {', '.join(missing_categories)}")
        
        # Check for invalid categories
        invalid_categories = matrix_categories - set(self.valid_categories)
        if invalid_categories:
            errors.append(f"Invalid categories: {', '.join(invalid_categories)}")
        
        # Check each category
        for category_key, skills in skill_matrix.items():
            # Extract base category name
            base_category = category_key.split(', frequency:')[0].strip()
            
            # Skip if invalid category
            if base_category not in self.valid_categories:
                continue
            
            # If skills list is not empty, check frequency format
            if skills:
                # Category should have frequency
                if ', frequency:' not in category_key:
                    errors.append(f"Category '{base_category}' has skills but missing frequency in key")
                
                # Check each skill
                for skill in skills:
                    # Extract base skill name
                    base_skill = skill.split(', frequency:')[0].strip()
                    
                    # Skill should have frequency
                    if ', frequency:' not in skill:
                        errors.append(f"Skill '{base_skill}' in '{base_category}' missing frequency")
                    
                    # Check if skill is valid for this category
                    if base_category in self.valid_skills:
                        valid_skills_set = self.valid_skills[base_category]
                        
                        # Case-insensitive check
                        if not any(base_skill.lower() == valid.lower() for valid in valid_skills_set):
                            errors.append(
                                f"Invalid skill '{base_skill}' in category '{base_category}'"
                            )
            else:
                # Empty skills list should NOT have frequency
                if ', frequency:' in category_key:
                    errors.append(f"Category '{base_category}' is empty but has frequency in key")
        
        is_valid = len(errors) == 0
        
        if not is_valid:
            logger.warning(f"⚠️ Skill matrix validation failed: {len(errors)} errors")
        
        return is_valid, errors
    
    def fix_skill_matrix(self, skill_matrix: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """
        Attempt to auto-fix common issues in skill matrix
        
        Args:
            skill_matrix: Skill matrix from LLM
        
        Returns:
            Fixed skill matrix
        """
        fixed_matrix = {}
        
        for category_key, skills in skill_matrix.items():
            # Extract base category and frequency
            base_category = category_key.split(', frequency:')[0].strip()
            
            # Skip invalid categories
            if base_category not in self.valid_categories:
                logger.warning(f"⚠️ Skipping invalid category: {base_category}")
                continue
            
            # Fix skills list
            fixed_skills = []
            if skills:
                for skill in skills:
                    # Extract base skill name
                    base_skill = skill.split(', frequency:')[0].strip()
                    
                    # Validate skill
                    if base_category in self.valid_skills:
                        valid_skills_set = self.valid_skills[base_category]
                        
                        # Find matching valid skill (case-insensitive)
                        matched_skill = None
                        for valid_skill in valid_skills_set:
                            if base_skill.lower() == valid_skill.lower():
                                matched_skill = valid_skill
                                break
                        
                        if matched_skill:
                            # Preserve frequency if present
                            if ', frequency:' in skill:
                                fixed_skills.append(skill)
                            else:
                                # Add default frequency
                                fixed_skills.append(f"{matched_skill}, frequency: 1")
                        else:
                            logger.debug(f"⚠️ Removing invalid skill: {base_skill} from {base_category}")
                
                # Calculate total frequency
                total_freq = 0
                for skill in fixed_skills:
                    if ', frequency:' in skill:
                        freq_str = skill.split(', frequency:')[1].strip()
                        try:
                            total_freq += int(freq_str)
                        except ValueError:
                            pass
                
                # Add to fixed matrix with proper category key
                if fixed_skills:
                    fixed_category_key = f"{base_category}, frequency: {total_freq}"
                    fixed_matrix[fixed_category_key] = fixed_skills
                else:
                    # Empty category (no frequency)
                    fixed_matrix[base_category] = []
            else:
                # Empty category (no frequency)
                fixed_matrix[base_category] = []
        
        # Add missing categories as empty
        for category in self.valid_categories:
            # Check if category exists (with or without frequency)
            exists = any(
                key.split(', frequency:')[0].strip() == category
                for key in fixed_matrix.keys()
            )
            if not exists:
                fixed_matrix[category] = []
        
        return fixed_matrix
    
    def extract_top_skills(
        self,
        skill_matrix: Dict[str, List[str]],
        top_n: int = 5
    ) -> List[Tuple[str, int]]:
        """
        Extract top N skills by frequency
        
        Args:
            skill_matrix: Skill matrix dictionary
            top_n: Number of top skills to return
        
        Returns:
            List of (skill_name, frequency) tuples, sorted by frequency
        """
        skill_freq_pairs = []
        
        for category_key, skills in skill_matrix.items():
            for skill in skills:
                if ', frequency:' in skill:
                    parts = skill.split(', frequency:')
                    if len(parts) == 2:
                        skill_name = parts[0].strip()
                        try:
                            freq = int(parts[1].strip())
                            skill_freq_pairs.append((skill_name, freq))
                        except ValueError:
                            continue
        
        # Sort by frequency (descending)
        skill_freq_pairs.sort(key=lambda x: x[1], reverse=True)
        
        return skill_freq_pairs[:top_n]
    
    def extract_primary_skills(
        self,
        skill_matrix: Dict[str, List[str]],
        min_frequency: int = 3
    ) -> List[str]:
        """
        Extract primary skills (high frequency skills)
        
        Args:
            skill_matrix: Skill matrix dictionary
            min_frequency: Minimum frequency threshold
        
        Returns:
            List of primary skill names
        """
        primary_skills = []
        
        for category_key, skills in skill_matrix.items():
            for skill in skills:
                if ', frequency:' in skill:
                    parts = skill.split(', frequency:')
                    if len(parts) == 2:
                        skill_name = parts[0].strip()
                        try:
                            freq = int(parts[1].strip())
                            if freq >= min_frequency:
                                primary_skills.append(skill_name)
                        except ValueError:
                            continue
        
        return primary_skills
    
    def calculate_skill_diversity(self, skill_matrix: Dict[str, List[str]]) -> float:
        """
        Calculate skill diversity score (0-1)
        Number of categories with skills / total categories
        
        Args:
            skill_matrix: Skill matrix dictionary
        
        Returns:
            Diversity score (0.0 to 1.0)
        """
        categories_with_skills = 0
        total_categories = len(self.valid_categories)
        
        for category_key, skills in skill_matrix.items():
            if skills:  # Non-empty skills list
                categories_with_skills += 1
        
        return categories_with_skills / total_categories if total_categories > 0 else 0.0


# Example usage and testing
if __name__ == "__main__":
    print("🔍 Testing Skill Analyzer")
    print("=" * 60)
    
    analyzer = SkillAnalyzer()
    
    # Test valid skill matrix
    valid_matrix = {
        "Framework/Library Expertise, frequency: 15": [
            "Node.js, frequency: 8",
            "Express.js, frequency: 5",
            "Jest, frequency: 2"
        ],
        "Asynchronous Programming, frequency: 5": [
            "Promises, frequency: 3",
            "async/await, frequency: 2"
        ],
        "API Design & Consumption": [],
        "Error Handling": [],
        "Frontend Development Skills": [],
        "Backend Development Skills": [],
        "DevOps & Deployment": [],
        "Advanced JavaScript Concepts": [],
        "Functional Programming": [],
        "Data Structures & Algorithms": [],
        "TypeScript": [],
        "Progressive Web Apps (PWA)": [],
        "Mobile Development with JavaScript": [],
        "Web Performance Optimization": [],
        "Event-Driven Architecture": [],
        "Dependency Management": [],
        "Graphical Data Visualization": []
    }
    
    is_valid, errors = analyzer.validate_skill_matrix(valid_matrix)
    print(f"✅ Valid matrix: {is_valid}")
    if errors:
        print(f"   Errors: {errors}")
    
    # Test top skills extraction
    top_skills = analyzer.extract_top_skills(valid_matrix, top_n=3)
    print(f"\n✅ Top 3 skills:")
    for skill, freq in top_skills:
        print(f"   - {skill}: {freq}")
    
    # Test skill diversity
    diversity = analyzer.calculate_skill_diversity(valid_matrix)
    print(f"\n✅ Skill diversity: {diversity:.2f}")
    
    print("\n✅ Skill analyzer working correctly!")