"""
Configuration Manager
Loads settings from config.yaml and provides easy access
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    """Centralized configuration management"""
    
    _instance = None  # Singleton pattern
    
    def __new__(cls):
        """Ensure only one Config instance exists (Singleton)"""
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration
        
        Args:
            config_path: Path to config.yaml (default: config/config.yaml)
        """
        # Only initialize once (Singleton pattern)
        if self._initialized:
            return
        
        if config_path is None:
            # Default to project root / config / config.yaml
            project_root = Path(__file__).parent.parent.parent
            config_path = project_root / "config" / "config.yaml"
        
        self.config_path = Path(config_path)
        self._config = self._load_config()
        self._initialized = True
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {self.config_path}\n"
                f"Please create config/config.yaml"
            )
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            if not config:
                raise ValueError("Config file is empty")
            
            return config
        
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML in config file: {e}")
    
    def get(self, path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation
        
        Args:
            path: Dot-separated path to config value (e.g., 'github.max_prs_to_fetch')
            default: Default value if path not found
        
        Returns:
            Configuration value or default
        
        Examples:
            >>> config = Config()
            >>> config.get('github.max_prs_to_fetch')
            500
            >>> config.get('github.api_rate_limit_delay')
            0.3
            >>> config.get('llm.model')
            'qwen/qwen-2.5-72b-instruct'
        """
        keys = path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        
        return value
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """
        Get entire configuration section
        
        Args:
            section: Top-level section name (e.g., 'github', 'llm')
        
        Returns:
            Dictionary of section configuration
        
        Examples:
            >>> config = Config()
            >>> github_config = config.get_section('github')
            >>> print(github_config['max_prs_to_fetch'])
            500
        """
        return self._config.get(section, {})
    
    def reload(self):
        """Reload configuration from file (useful for hot-reloading)"""
        self._config = self._load_config()
        print(f"✅ Configuration reloaded from {self.config_path}")
    
    def __repr__(self):
        return f"Config(path={self.config_path})"


# Convenience function for quick access
def get_config() -> Config:
    """Get the singleton Config instance"""
    return Config()


# Example usage and testing
if __name__ == "__main__":
    # Test configuration loading
    config = Config()
    
    print("🔧 Configuration Test")
    print("=" * 50)
    
    # Test basic access
    print(f"GitHub max PRs: {config.get('github.max_prs_to_fetch')}")
    print(f"LLM model: {config.get('llm.model')}")
    print(f"Batch size: {config.get('profile_generation.batch_size')}")
    print(f"Top K reviewers: {config.get('reviewer_assignment.top_k_reviewers')}")
    
    # Test default values
    print(f"Non-existent key: {config.get('non.existent.key', 'DEFAULT_VALUE')}")
    
    # Test section access
    github_config = config.get_section('github')
    print(f"\nGitHub section: {github_config}")
    
    print("\n✅ Configuration loaded successfully!")