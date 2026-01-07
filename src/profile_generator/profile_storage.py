"""
Profile Storage Manager
Manages hybrid storage: JSON files (source of truth) + SQLite (query cache)
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from src.utils import get_logger, get_config, save_json, load_json

logger = get_logger(__name__)


class ProfileStorage:
    """Manages profile storage in JSON and SQLite"""
    
    def __init__(self, db_path: str = "data/cache/reviewers.db", json_dir: str = "data/profiles/reviewers"):
        """
        Initialize profile storage
        
        Args:
            db_path: Path to SQLite database
            json_dir: Directory for JSON profile files
        """
        self.config = get_config()
        self.db_path = Path(db_path)
        self.json_dir = Path(json_dir)
        
        # Create directories
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.json_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
        
        logger.info(f"✅ Profile storage initialized (DB: {self.db_path}, JSON: {self.json_dir})")
    
    def _init_database(self):
        """Initialize database schema"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # Table 1: Reviewer Profiles (main table)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviewer_profiles (
                reviewer_name TEXT PRIMARY KEY,
                experience_level TEXT,
                programming_languages TEXT,
                primary_skills TEXT,
                summary TEXT,
                javascript_skill_matrix TEXT,
                total_reviews INTEGER,
                total_comments INTEGER,
                total_prs INTEGER,
                repos TEXT,
                profile_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Table 2: Reviewer Skills (for fast skill-based queries)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviewer_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reviewer_name TEXT,
                skill_name TEXT,
                skill_category TEXT,
                frequency INTEGER,
                FOREIGN KEY (reviewer_name) REFERENCES reviewer_profiles(reviewer_name)
            )
        """)
        
        # Table 3: Assignment History (track suggestions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assignment_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_number INTEGER,
                repo_name TEXT,
                pr_author TEXT,
                suggested_reviewers TEXT,
                assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confidence_score REAL
            )
        """)
        
        # Indexes for performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_experience 
            ON reviewer_profiles(experience_level)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_total_reviews 
            ON reviewer_profiles(total_reviews)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_skill_name 
            ON reviewer_skills(skill_name)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_reviewer_skill 
            ON reviewer_skills(reviewer_name, skill_name)
        """)
        
        conn.commit()
        conn.close()
        
        logger.debug("✅ Database schema initialized")
    
    def save_profile(self, profile_data: Dict) -> Tuple[str, bool]:
        """
        Save profile to both JSON and SQLite
        
        Args:
            profile_data: Complete profile data dictionary
        
        Returns:
            Tuple of (json_filepath, success)
        """
        reviewer_name = profile_data.get('reviewer_name')
        if not reviewer_name:
            logger.error("❌ Profile missing reviewer_name")
            return "", False
        
        try:
            # Step 1: Save to JSON (source of truth)
            json_path = self._save_to_json(profile_data)
            
            # Step 2: Sync to SQLite (query cache)
            self._sync_to_database(profile_data)
            
            logger.info(f"✅ Saved profile for {reviewer_name}")
            return str(json_path), True
            
        except Exception as e:
            logger.error(f"❌ Failed to save profile for {reviewer_name}: {e}")
            return "", False
    
    def _save_to_json(self, profile_data: Dict) -> Path:
        """Save profile to JSON file"""
        reviewer_name = profile_data['reviewer_name']
        timestamp = profile_data.get('generated_at', datetime.now().strftime('%Y%m%d_%H%M%S'))
        
        filename = f"{reviewer_name}_reviewer_profile_{timestamp}.json"
        filepath = self.json_dir / filename
        
        save_json(str(filepath), profile_data)
        logger.debug(f"💾 Saved JSON: {filepath}")
        
        return filepath
    
    def _sync_to_database(self, profile_data: Dict):
        """Sync profile to SQLite database"""
        reviewer_name = profile_data['reviewer_name']
        stats = profile_data.get('stats', {})
        profile = profile_data.get('profile', {})
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        try:
            # Insert or replace main profile
            cursor.execute("""
                INSERT OR REPLACE INTO reviewer_profiles (
                    reviewer_name, experience_level, programming_languages,
                    primary_skills, summary, javascript_skill_matrix,
                    total_reviews, total_comments, total_prs, repos,
                    profile_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                reviewer_name,
                profile.get('experience_level', ''),
                json.dumps(profile.get('programming_languages', [])),
                json.dumps(profile.get('primary_skills', [])),
                profile.get('summary', ''),
                json.dumps(profile.get('javascript_skill_matrix', {})),
                stats.get('total_reviews', 0),
                stats.get('total_comments', 0),
                stats.get('total_prs', 0),
                json.dumps(stats.get('repos', [])),
                json.dumps(profile_data),
                datetime.now().isoformat()
            ))
            
            # Delete old skills for this reviewer
            cursor.execute("DELETE FROM reviewer_skills WHERE reviewer_name = ?", (reviewer_name,))
            
            # Insert skills
            skill_matrix = profile.get('javascript_skill_matrix', {})
            for category_key, skills in skill_matrix.items():
                if not skills:  # Skip empty categories
                    continue
                
                # Extract base category name
                base_category = category_key.split(', frequency:')[0].strip()
                
                for skill in skills:
                    if ', frequency:' in skill:
                        parts = skill.split(', frequency:')
                        skill_name = parts[0].strip()
                        try:
                            frequency = int(parts[1].strip())
                        except (ValueError, IndexError):
                            frequency = 0
                        
                        cursor.execute("""
                            INSERT INTO reviewer_skills (
                                reviewer_name, skill_name, skill_category, frequency
                            ) VALUES (?, ?, ?, ?)
                        """, (reviewer_name, skill_name, base_category, frequency))
            
            conn.commit()
            logger.debug(f"💾 Synced to DB: {reviewer_name}")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Database sync failed for {reviewer_name}: {e}")
            raise
        finally:
            conn.close()
    
    def get_profile(self, reviewer_name: str) -> Optional[Dict]:
        """
        Get profile (from SQLite cache or JSON fallback)
        
        Args:
            reviewer_name: Reviewer username
        
        Returns:
            Profile data dictionary or None
        """
        # Try SQLite first (fast)
        profile = self._get_from_database(reviewer_name)
        
        if profile:
            return profile
        
        # Fallback to JSON
        profile = self._get_from_json(reviewer_name)
        
        if profile:
            # Sync to DB for next time
            try:
                self._sync_to_database(profile)
            except Exception as e:
                logger.warning(f"⚠️ Could not sync {reviewer_name} to DB: {e}")
        
        return profile
    
    def _get_from_database(self, reviewer_name: str) -> Optional[Dict]:
        """Get profile from SQLite"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT profile_json FROM reviewer_profiles 
            WHERE reviewer_name = ?
        """, (reviewer_name,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                logger.warning(f"⚠️ Invalid JSON in DB for {reviewer_name}")
                return None
        
        return None
    
    def _get_from_json(self, reviewer_name: str) -> Optional[Dict]:
        """Get profile from JSON files"""
        # Find most recent profile file for this reviewer
        pattern = f"{reviewer_name}_reviewer_profile_*.json"
        files = sorted(self.json_dir.glob(pattern), reverse=True)
        
        if files:
            try:
                return load_json(str(files[0]))
            except Exception as e:
                logger.error(f"❌ Failed to load JSON for {reviewer_name}: {e}")
        
        return None
    
    def list_reviewers(self) -> List[str]:
        """
        Get list of all reviewer names
        
        Returns:
            List of reviewer usernames
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT reviewer_name FROM reviewer_profiles ORDER BY reviewer_name")
        reviewers = [row[0] for row in cursor.fetchall()]
        
        conn.close()
        return reviewers
    
    def query_reviewers_by_skill(
        self,
        skill_name: str,
        min_frequency: int = 1
    ) -> List[Tuple[str, int]]:
        """
        Query reviewers by skill
        
        Args:
            skill_name: Skill name to search for
            min_frequency: Minimum frequency threshold
        
        Returns:
            List of (reviewer_name, frequency) tuples, sorted by frequency
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT reviewer_name, frequency
            FROM reviewer_skills
            WHERE skill_name = ? AND frequency >= ?
            ORDER BY frequency DESC
        """, (skill_name, min_frequency))
        
        results = cursor.fetchall()
        conn.close()
        
        return results
    
    def query_reviewers_by_experience(self, experience_level: str) -> List[str]:
        """
        Query reviewers by experience level
        
        Args:
            experience_level: Experience level (Junior/Mid/Senior/Lead)
        
        Returns:
            List of reviewer names
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT reviewer_name FROM reviewer_profiles
            WHERE experience_level = ?
            ORDER BY total_reviews DESC
        """, (experience_level,))
        
        reviewers = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        return reviewers
    
    def get_statistics(self) -> Dict:
        """
        Get storage statistics
        
        Returns:
            Dictionary of statistics
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # Count profiles
        cursor.execute("SELECT COUNT(*) FROM reviewer_profiles")
        total_profiles = cursor.fetchone()[0]
        
        # Count by experience level
        cursor.execute("""
            SELECT experience_level, COUNT(*) 
            FROM reviewer_profiles 
            GROUP BY experience_level
        """)
        by_experience = dict(cursor.fetchall())
        
        # Count unique skills
        cursor.execute("SELECT COUNT(DISTINCT skill_name) FROM reviewer_skills")
        unique_skills = cursor.fetchone()[0]
        
        conn.close()
        
        # Count JSON files
        json_files = len(list(self.json_dir.glob("*_reviewer_profile_*.json")))
        
        return {
            'total_profiles': total_profiles,
            'by_experience_level': by_experience,
            'unique_skills': unique_skills,
            'json_files': json_files
        }
    
    def track_assignment(
        self,
        pr_number: int,
        repo_name: str,
        pr_author: str,
        suggested_reviewers: List[str],
        confidence_score: float
    ):
        """
        Track reviewer assignment in history
        
        Args:
            pr_number: PR number
            repo_name: Repository name
            pr_author: PR author username
            suggested_reviewers: List of suggested reviewer names
            confidence_score: Assignment confidence score
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO assignment_history (
                pr_number, repo_name, pr_author, 
                suggested_reviewers, confidence_score
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            pr_number,
            repo_name,
            pr_author,
            json.dumps(suggested_reviewers),
            confidence_score
        ))
        
        conn.commit()
        conn.close()
        
        logger.debug(f"📊 Tracked assignment for PR #{pr_number}")


# Example usage and testing
if __name__ == "__main__":
    print("💾 Testing Profile Storage")
    print("=" * 60)
    
    # Initialize storage
    storage = ProfileStorage(
        db_path="data/cache/reviewers.db",
        json_dir="data/profiles/reviewers"
    )
    
    # Create sample profile
    sample_profile = {
        "reviewer_name": "test_reviewer",
        "generated_at": "20250107_120000",
        "stats": {
            "total_reviews": 10,
            "total_comments": 5,
            "total_prs": 8,
            "repos": ["moment", "lodash"]
        },
        "profile": {
            "experience_level": "Senior",
            "programming_languages": ["JavaScript"],
            "primary_skills": ["Node.js", "Express.js"],
            "summary": "Experienced JavaScript reviewer",
            "javascript_skill_matrix": {
                "Framework/Library Expertise, frequency: 15": [
                    "Node.js, frequency: 8",
                    "Express.js, frequency: 7"
                ],
                "Asynchronous Programming": [],
                "API Design & Consumption": []
            }
        }
    }
    
    # Test save
    print("\n💾 Saving profile...")
    filepath, success = storage.save_profile(sample_profile)
    if success:
        print(f"✅ Saved to: {filepath}")
    
    # Test retrieve
    print("\n📖 Retrieving profile...")
    retrieved = storage.get_profile("test_reviewer")
    if retrieved:
        print(f"✅ Retrieved: {retrieved['reviewer_name']}")
    
    # Test query by skill
    print("\n🔍 Querying by skill...")
    results = storage.query_reviewers_by_skill("Node.js", min_frequency=5)
    print(f"✅ Found {len(results)} reviewers with Node.js (freq >= 5)")
    for name, freq in results:
        print(f"   - {name}: {freq}")
    
    # Test statistics
    print("\n📊 Storage statistics...")
    stats = storage.get_statistics()
    print(f"✅ Total profiles: {stats['total_profiles']}")
    print(f"✅ Unique skills: {stats['unique_skills']}")
    print(f"✅ JSON files: {stats['json_files']}")
    
    print("\n✅ Profile storage working correctly!")