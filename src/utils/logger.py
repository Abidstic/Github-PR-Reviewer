"""
Logging Configuration
Provides centralized logging for the entire application
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from logging.handlers import RotatingFileHandler
from datetime import datetime


class Logger:
    """Centralized logger configuration"""
    
    _loggers = {}  # Cache of configured loggers
    
    @staticmethod
    def setup(
        name: str,
        log_level: str = "INFO",
        log_file: Optional[str] = None,
        console: bool = True,
        max_bytes: int = 10_000_000,  # 10MB
        backup_count: int = 5
    ) -> logging.Logger:
        """
        Set up a logger with file and/or console handlers
        
        Args:
            name: Logger name (usually __name__)
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Path to log file (None for console only)
            console: Whether to also log to console
            max_bytes: Maximum log file size before rotation
            backup_count: Number of backup log files to keep
        
        Returns:
            Configured logger instance
        
        Examples:
            >>> logger = Logger.setup(__name__)
            >>> logger.info("This is an info message")
            >>> logger.error("This is an error message")
        """
        # Return cached logger if already configured
        if name in Logger._loggers:
            return Logger._loggers[name]
        
        # Create logger
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, log_level.upper()))
        
        # Prevent duplicate handlers
        if logger.handlers:
            logger.handlers.clear()
        
        # Create formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Add file handler if log_file specified
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setLevel(getattr(logging, log_level.upper()))
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        # Add console handler if requested
        if console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(getattr(logging, log_level.upper()))
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        
        # Cache logger
        Logger._loggers[name] = logger
        
        return logger
    
    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        """
        Get an existing logger or create a new one with default settings
        
        Args:
            name: Logger name
        
        Returns:
            Logger instance
        """
        if name in Logger._loggers:
            return Logger._loggers[name]
        
        # Create with default settings
        return Logger.setup(name)


def get_logger(name: str, log_level: str = "INFO") -> logging.Logger:
    """
    Convenience function to get a logger
    
    Args:
        name: Logger name (usually __name__)
        log_level: Logging level
    
    Returns:
        Configured logger
    
    Examples:
        >>> from src.utils.logger import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("Application started")
    """
    # Get log settings from config if available
    try:
        from src.utils.config import get_config
        config = get_config()
        
        log_level = config.get('logging.level', log_level)
        log_file = config.get('logging.file', None)
        console = config.get('logging.console', True)
    except:
        # Fallback to defaults if config not available
        log_file = None
        console = True
    
    return Logger.setup(
        name=name,
        log_level=log_level,
        log_file=log_file,
        console=console
    )


# Example usage and testing
if __name__ == "__main__":
    # Test logger
    logger = get_logger(__name__)
    
    print("📝 Logger Test")
    print("=" * 50)
    
    logger.debug("This is a DEBUG message")
    logger.info("This is an INFO message")
    logger.warning("This is a WARNING message")
    logger.error("This is an ERROR message")
    logger.critical("This is a CRITICAL message")
    
    print("\n✅ Logger working correctly!")