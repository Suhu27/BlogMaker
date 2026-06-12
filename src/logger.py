"""
Structured logging setup for BlogMaker.

Creates date-stamped log files in the configured log directory
and outputs to both file and console.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logging(log_dir: str = "logs", level: int = logging.INFO) -> logging.Logger:
    """
    Configure structured logging with file and console handlers.

    Args:
        log_dir: Directory to store log files.
        level: Logging level (default: INFO).

    Returns:
        Configured root logger for the application.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = log_path / f"{today}.log"

    # Create formatter
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] [%(name)-20s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # Root logger for BlogMaker
    logger = logging.getLogger("blogmaker")
    logger.setLevel(level)

    # Avoid duplicate handlers on re-init
    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    logger.info("Logging initialized — file: %s", log_file)
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a child logger under the blogmaker namespace.

    Args:
        name: Module name for the logger.

    Returns:
        Logger instance.
    """
    return logging.getLogger(f"blogmaker.{name}")
