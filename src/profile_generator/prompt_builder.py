"""
Prompt Builder
Constructs prompts with proper context for profile generation
"""

import json
from typing import Dict, List, Any

from src.utils import get_logger, get_config

logger = get_logger(__name__)


class PromptBuilder:
    """Builds prompts for LLM with proper context"""
    
    def __init__(self):
        """Initialize prompt builder"""
        self.config = get_config()
        
        # Load JavaScript skill categories from config
        self.skill_categories = self.config.get('profile_generation.skill_categories', [])
        
        # Detailed skill definitions (from your notebooks)
        self.js_skill_definitions = {
            "Framework/Library Expertise": [
                "Frontend Frameworks: React, Angular, Vue.js, Svelte, Ember.js, Backbone.js, Mithril, Preact, jQuery, moment.js",
                "Backend Frameworks: Node.js, Express.js, Koa.js",
                "State Management: Redux, Context API, Zustand",
                "Testing Libraries: Jest, Mocha, Chai",
                "Static Site Generation/Server-Side Rendering: Next.js, Nuxt.js"
            ],
            "Asynchronous Programming": [
                "async/await", "Promises", "Callbacks", "Event Loop", "Concurrency Control"
            ],
            "API Design & Consumption": [
                "RESTful APIs", "GraphQL", "WebSockets", 
                "Authentication & Authorization", "API Error Handling", "Rate Limiting"
            ],
            "Error Handling": [
                "Try-Catch", "Custom Error Classes", "Error Boundaries"
            ],
            "Frontend Development Skills": [
                "DOM Manipulation"
            ],
            "Backend Development Skills": [
                "Server-Side Logic", "Database Integration", "API Endpoints",
                "Authentication/Authorization", "Middleware", "Microservices", "Caching"
            ],
            "DevOps & Deployment": [
                "CI/CD Pipelines", "Containerization", "Cloud Providers",
                "Load Balancing", "Web Servers"
            ],
            "Advanced JavaScript Concepts": [
                "Closures", "Higher-Order Functions", "Prototypes & Inheritance",
                "Module Systems", "Event Delegation", "Memory Management"
            ],
            "Functional Programming": [
                "Immutability", "Pure Functions", "Declarative Programming", "Composition"
            ],
            "Data Structures & Algorithms": [
                "Data Structures", "Searching and Sorting Algorithms", "Recursion", "Big O Notation"
            ],
            "TypeScript": [
                "Type Definitions", "Generics", "Type Inference",
                "Modules & Namespaces", "Type Narrowing"
            ],
            "Progressive Web Apps (PWA)": [
                "Service Workers", "Web Push Notifications", "Caching Strategies",
                "App Shell Model", "Manifest File"
            ],
            "Mobile Development with JavaScript": [
                "React Native", "Ionic", "Cordova/PhoneGap"
            ],
            "Web Performance Optimization": [
                "Lazy Loading", "Code Splitting", "Minification & Compression",
                "Critical Rendering Path Optimization", "Preloading & Prefetching"
            ],
            "Event-Driven Architecture": [
                "Event Emitters", "Pub/Sub Model"
            ],
            "Dependency Management": [
                "npm/yarn", "Package-lock.json & Yarn.lock"
            ],
            "Graphical Data Visualization": [
                "D3.js", "Chart.js", "WebGL & Three.js"
            ]
        }
        
        logger.info("✅ Prompt builder initialized")
    
    def build_skills_analysis_variables(
        self,
        reviewer_name: str,
        review_data: List[Dict],
        max_reviews: int = 20
    ) -> Dict[str, str]:
        """
        Build variables for skills analysis prompt
        
        Args:
            reviewer_name: Reviewer username
            review_data: List of review details
            max_reviews: Maximum reviews to include
        
        Returns:
            Dictionary of template variables
        """
        # Limit review data size
        limited_reviews = review_data[:max_reviews]
        
        # Summarize review data
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
            if review.get('description') and len(review['description']) < 500:
                summary['pr_description'] = review['description'][:300]
            
            # Add review body if available and short
            if review.get('review_body') and len(review['review_body']) < 500:
                summary['review_comment'] = review['review_body'][:300]
            
            review_summary.append(summary)
        
        return {
            'reviewer_name': reviewer_name,
            'review_data': json.dumps(review_summary, indent=2)
        }
    
    def build_profile_generation_variables(
        self,
        reviewer_name: str,
        skills_analysis: str,
        review_count: int,
        repo_list: str,
        format_instructions: str = ""
    ) -> Dict[str, str]:
        """
        Build variables for profile generation prompt
        
        Args:
            reviewer_name: Reviewer username
            skills_analysis: LLM skills analysis result
            review_count: Total review count
            repo_list: Comma-separated repository list
            format_instructions: Pydantic format instructions
        
        Returns:
            Dictionary of template variables
        """
        # Format valid categories
        valid_categories = "\n".join([f'   - "{cat}"' for cat in self.skill_categories])
        
        # Format skill definitions
        js_categories = "\n".join([
            f"{cat}: {', '.join(skills)}"
            for cat, skills in self.js_skill_definitions.items()
        ])
        
        return {
            'reviewer_name': reviewer_name,
            'skills_analysis': skills_analysis,
            'review_count': str(review_count),
            'repo_list': repo_list,
            'valid_categories': valid_categories,
            'js_categories': js_categories,
            'format_instructions': format_instructions
        }
    
    def get_js_skill_definitions(self) -> Dict[str, List[str]]:
        """Get JavaScript skill definitions"""
        return self.js_skill_definitions.copy()
    
    def get_valid_categories(self) -> List[str]:
        """Get list of valid skill categories"""
        return self.skill_categories.copy()


# Example usage and testing
if __name__ == "__main__":
    print("📋 Testing Prompt Builder")
    print("=" * 60)
    
    builder = PromptBuilder()
    
    # Test skills analysis variables
    sample_reviews = [
        {
            'title': 'Fix Express.js routing issue',
            'review_state': 'APPROVED',
            'additions': 50,
            'deletions': 10
        }
    ]
    
    skills_vars = builder.build_skills_analysis_variables(
        'testuser',
        sample_reviews
    )
    
    print(f"✅ Skills analysis variables:")
    print(f"   Reviewer: {skills_vars['reviewer_name']}")
    print(f"   Review data length: {len(skills_vars['review_data'])} chars")
    
    # Test profile generation variables
    profile_vars = builder.build_profile_generation_variables(
        'testuser',
        'Sample skills analysis',
        10,
        'moment, lodash'
    )
    
    print(f"\n✅ Profile generation variables:")
    print(f"   Reviewer: {profile_vars['reviewer_name']}")
    print(f"   Review count: {profile_vars['review_count']}")
    print(f"   Valid categories: {len(builder.get_valid_categories())}")
    
    print("\n✅ Prompt builder working correctly!")