"""
Helper Utilities
Common utility functions used across the project
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from functools import wraps

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# File I/O Helpers
# ============================================================================

def load_json(file_path: str) -> Dict[str, Any]:
    """
    Load JSON file
    
    Args:
        file_path: Path to JSON file
    
    Returns:
        Parsed JSON as dictionary
    
    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file is invalid JSON
    """
    file_path = Path(file_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {file_path}: {e}")
        raise


def save_json(file_path: str, data: Dict[str, Any], indent: int = 2):
    """
    Save data as JSON file
    
    Args:
        file_path: Path to save JSON file
        data: Data to save
        indent: JSON indentation (default: 2)
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        logger.debug(f"Saved JSON to {file_path}")
    except Exception as e:
        logger.error(f"Failed to save JSON to {file_path}: {e}")
        raise


def ensure_directory(dir_path: str) -> Path:
    """
    Ensure directory exists, create if it doesn't
    
    Args:
        dir_path: Directory path
    
    Returns:
        Path object
    """
    dir_path = Path(dir_path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


# ============================================================================
# Time & Date Helpers
# ============================================================================

def get_timestamp(format: str = "%Y%m%d_%H%M%S") -> str:
    """
    Get current timestamp as formatted string
    
    Args:
        format: strftime format string
    
    Returns:
        Formatted timestamp
    
    Examples:
        >>> get_timestamp()
        '20250106_143022'
        >>> get_timestamp("%Y-%m-%d")
        '2025-01-06'
    """
    return datetime.now().strftime(format)


def parse_github_timestamp(timestamp_str: str) -> datetime:
    """
    Parse GitHub API timestamp to datetime
    
    Args:
        timestamp_str: GitHub timestamp (e.g., '2024-01-15T10:30:00Z')
    
    Returns:
        datetime object
    """
    # Remove 'Z' and parse
    if timestamp_str.endswith('Z'):
        timestamp_str = timestamp_str[:-1] + '+00:00'
    
    return datetime.fromisoformat(timestamp_str)


# ============================================================================
# Retry & Rate Limiting Helpers
# ============================================================================

def retry_on_failure(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    Decorator to retry function on failure
    
    Args:
        max_attempts: Maximum number of attempts
        delay: Initial delay between retries (seconds)
        backoff: Multiplier for delay after each retry
    
    Examples:
        >>> @retry_on_failure(max_attempts=3, delay=1.0)
        >>> def fetch_data():
        >>>     # This will retry up to 3 times if it fails
        >>>     return requests.get('https://api.example.com')
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    
                    logger.warning(
                        f"{func.__name__} failed (attempt {attempt}/{max_attempts}): {e}. "
                        f"Retrying in {current_delay}s..."
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff
            
        return wrapper
    return decorator


def rate_limit(calls_per_second: float = 1.0):
    """
    Decorator to rate limit function calls
    
    Args:
        calls_per_second: Maximum calls per second
    
    Examples:
        >>> @rate_limit(calls_per_second=2.0)  # Max 2 calls per second
        >>> def api_call():
        >>>     return requests.get('https://api.example.com')
    """
    min_interval = 1.0 / calls_per_second
    last_called = [0.0]
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            wait_time = min_interval - elapsed
            
            if wait_time > 0:
                time.sleep(wait_time)
            
            result = func(*args, **kwargs)
            last_called[0] = time.time()
            
            return result
        return wrapper
    return decorator


# ============================================================================
# Data Processing Helpers
# ============================================================================

def safe_get(data: Dict, path: str, default: Any = None) -> Any:
    """
    Safely get nested dictionary value using dot notation
    
    Args:
        data: Dictionary to search
        path: Dot-separated path (e.g., 'user.profile.name')
        default: Default value if path not found
    
    Returns:
        Value at path or default
    
    Examples:
        >>> data = {'user': {'profile': {'name': 'Alice'}}}
        >>> safe_get(data, 'user.profile.name')
        'Alice'
        >>> safe_get(data, 'user.age', default=25)
        25
    """
    keys = path.split('.')
    value = data
    
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
            if value is None:
                return default
        else:
            return default
    
    return value


def flatten_dict(data: Dict, parent_key: str = '', separator: str = '.') -> Dict:
    """
    Flatten nested dictionary
    
    Args:
        data: Dictionary to flatten
        parent_key: Parent key prefix
        separator: Key separator
    
    Returns:
        Flattened dictionary
    
    Examples:
        >>> data = {'a': {'b': {'c': 1}}}
        >>> flatten_dict(data)
        {'a.b.c': 1}
    """
    items = []
    
    for key, value in data.items():
        new_key = f"{parent_key}{separator}{key}" if parent_key else key
        
        if isinstance(value, dict):
            items.extend(flatten_dict(value, new_key, separator).items())
        else:
            items.append((new_key, value))
    
    return dict(items)


def chunk_list(data: List, chunk_size: int) -> List[List]:
    """
    Split list into chunks
    
    Args:
        data: List to chunk
        chunk_size: Size of each chunk
    
    Returns:
        List of chunks
    
    Examples:
        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]


# ============================================================================
# String Helpers
# ============================================================================

def truncate_string(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncate string to maximum length
    
    Args:
        text: String to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated
    
    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing invalid characters
    
    Args:
        filename: Original filename
    
    Returns:
        Sanitized filename
    """
    invalid_chars = '<>:"/\\|?*'
    
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    return filename


# ============================================================================
# Validation Helpers
# ============================================================================

def is_valid_github_token(token: str) -> bool:
    """
    Basic validation for GitHub token format
    
    Args:
        token: GitHub token to validate
    
    Returns:
        True if format is valid
    """
    if not token:
        return False
    
    # GitHub tokens start with 'ghp_', 'gho_', 'ghu_', or 'ghs_'
    valid_prefixes = ('ghp_', 'gho_', 'ghu_', 'ghs_', 'github_pat_')
    
    return any(token.startswith(prefix) for prefix in valid_prefixes)


# Example usage and testing
if __name__ == "__main__":
    print("🔧 Helper Utilities Test")
    print("=" * 50)
    
    # Test JSON operations
    test_data = {"name": "Test", "value": 123}
    test_file = "temp_test.json"
    
    save_json(test_file, test_data)
    loaded_data = load_json(test_file)
    print(f"JSON test: {loaded_data}")
    
    # Clean up
    os.remove(test_file)
    
    # Test safe_get
    nested = {"user": {"profile": {"name": "Alice"}}}
    print(f"Safe get: {safe_get(nested, 'user.profile.name')}")
    print(f"Safe get with default: {safe_get(nested, 'user.age', 25)}")
    
    # Test chunking
    data_list = list(range(1, 11))
    chunks = chunk_list(data_list, 3)
    print(f"Chunks: {chunks}")
    
    # Test timestamp
    print(f"Timestamp: {get_timestamp()}")
    
    print("\n✅ All helpers working correctly!")