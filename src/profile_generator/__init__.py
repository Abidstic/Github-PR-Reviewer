"""
Profile generation modules for GitHub Reviewer AI.

Phase 6: UnifiedProfileBuilder replaces ReviewerProfileBuilder and
DeveloperProfileBuilder.  ProfileStorage replaced by WindowManager.
Legacy modules kept on disk for reference but not imported here.

Heavy dependencies (langchain, pydantic) are loaded lazily — import
specific submodules directly when needed rather than relying on this
package-level export.
"""

from src.profile_generator.skill_analyzer import SkillAnalyzer

__all__ = [
    'SkillAnalyzer',
]
