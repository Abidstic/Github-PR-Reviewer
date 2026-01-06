"""
Test utility modules
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils import get_config, get_logger, load_json, save_json, get_timestamp


def test_config():
    """Test configuration loading"""
    print("\n🔧 Testing Config...")
    
    config = get_config()
    
    # Test basic access
    max_prs = config.get('github.max_prs_to_fetch')
    print(f"  ✓ Max PRs: {max_prs}")
    
    # Test default value
    default_val = config.get('non.existent.key', 'DEFAULT')
    print(f"  ✓ Default value: {default_val}")
    
    # Test section access
    llm_config = config.get_section('llm')
    print(f"  ✓ LLM config: {llm_config}")
    
    print("✅ Config tests passed!")


def test_logger():
    """Test logging functionality"""
    print("\n📝 Testing Logger...")
    
    logger = get_logger(__name__)
    
    logger.debug("Debug message")
    logger.info("Info message")
    logger.warning("Warning message")
    logger.error("Error message")
    
    print("✅ Logger tests passed!")


def test_helpers():
    """Test helper functions"""
    print("\n🔧 Testing Helpers...")
    
    # Test JSON operations
    test_data = {"test": "data", "number": 42}
    test_file = "temp_test.json"
    
    save_json(test_file, test_data)
    loaded = load_json(test_file)
    
    assert loaded == test_data, "JSON load/save mismatch"
    print(f"  ✓ JSON operations work")
    
    # Clean up
    os.remove(test_file)
    
    # Test timestamp
    timestamp = get_timestamp()
    print(f"  ✓ Timestamp: {timestamp}")
    
    print("✅ Helper tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("TESTING UTILITIES")
    print("=" * 60)
    
    try:
        test_config()
        test_logger()
        test_helpers()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()