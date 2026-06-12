"""
Configuration loader for BlogMaker.

Loads settings from config.yaml and merges environment variables.
Provides a validated, type-safe AppConfig dataclass.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.logger import get_logger

logger = get_logger("config")


@dataclass
class AppConfig:
    """Application configuration loaded from config.yaml and environment."""

    # Article structure
    article_words: int = 750
    executive_summary_words: int = 150
    linkedin_angles: int = 3
    key_takeaways: int = 5
    counterpoints: int = 3
    key_concepts_count: int = 5

    # AI model
    gemini_model: str = "gemini-2.5-pro"
    search_provider: str = "gemini"

    # Output toggles
    enable_email: bool = True
    enable_pdf: bool = True
    enable_html: bool = True
    enable_markdown: bool = True

    # Email
    recipient_email: str = "user@example.com"
    sender_email: str = "newsletter@yourdomain.com"
    email_subject_prefix: str = "Daily Research Brief"

    # File paths
    topics_file: str = "topics.xlsx"
    output_dir: str = "output"
    log_dir: str = "logs"

    # Retry settings
    max_retries: int = 3
    retry_delay_seconds: int = 2

    # Source tier preferences (injected into research prompts at runtime)
    preferred_source_tiers: dict[str, list[str]] = field(default_factory=dict)

    # Practitioner layer (Layer 2 research -- YouTube, podcasts, Substack)
    practitioner_layer_enabled: bool = True
    practitioner_topic_keywords: list[str] = field(default_factory=lambda: [
        "job", "jobs", "employment", "workforce", "career", "work",
        "labor", "labour", "displacement", "automation", "future of work",
        "layoff", "hiring", "opinion", "debate", "controversy",
        "ethical", "ethics", "society", "societal", "regulation",
        "policy", "bias", "fairness", "safety", "alignment", "risk",
    ])

    # Article writing persona & style
    linkedin_post_persona: str = (
        "Senior software engineer / solutions architect, ~50 years old, "
        "deep SAP ecosystem background, current focus on AI in enterprise software, "
        "Microsoft Copilot, and practical AI deployment at scale. "
        "Reads this brief each morning then writes their own LinkedIn post."
    )
    banned_phrases: list[str] = field(default_factory=lambda: [
        "game-changer",
        "revolutionary",
        "transformative",
        "unlock potential",
        "unlock the power",
        "in today's fast-paced world",
        "in today's rapidly evolving",
        "leverage",
        "synergy",
        "paradigm shift",
        "cutting-edge",
        "state-of-the-art",
        "groundbreaking",
        "seamlessly",
        "empower",
    ])

    # Scheduler
    daily_run_time: str = "07:00"
    pipeline_timeout_seconds: int = 600

    # Cost tracking
    enable_cost_tracking: bool = True

    # Testing mode
    testing_mode: bool = False

    # API keys (from environment only -- never from YAML)
    gemini_api_key: str = ""
    resend_api_key: str = ""


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """
    Load configuration from YAML file and environment variables.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        Validated AppConfig instance.

    Raises:
        FileNotFoundError: If config file does not exist.
        ValueError: If required configuration values are missing or invalid.
    """
    load_dotenv()

    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            "Create a config.yaml file or copy from config.yaml.example"
        )

    with open(config_file, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    logger.info("Loaded configuration from %s", config_path)

    # Default persona and banned phrases (overridable from YAML)
    default_persona = (
        "Senior software engineer / solutions architect, ~50 years old, "
        "deep SAP ecosystem background, current focus on AI in enterprise software, "
        "Microsoft Copilot, and practical AI deployment at scale. "
        "Reads this brief each morning then writes their own LinkedIn post."
    )
    default_banned_phrases = [
        "game-changer", "revolutionary", "transformative",
        "unlock potential", "unlock the power",
        "in today's fast-paced world", "in today's rapidly evolving",
        "leverage", "synergy", "paradigm shift",
        "cutting-edge", "state-of-the-art", "groundbreaking",
        "seamlessly", "empower",
    ]
    default_practitioner_keywords = [
        "job", "jobs", "employment", "workforce", "career", "work",
        "labor", "labour", "displacement", "automation", "future of work",
        "layoff", "hiring", "opinion", "debate", "controversy",
        "ethical", "ethics", "society", "societal", "regulation",
        "policy", "bias", "fairness", "safety", "alignment", "risk",
    ]

    config = AppConfig(
        # Article structure
        article_words=_safe_int(raw.get("article_words"), 750),
        executive_summary_words=_safe_int(raw.get("executive_summary_words"), 150),
        linkedin_angles=_safe_int(raw.get("linkedin_angles"), 3),
        key_takeaways=_safe_int(raw.get("key_takeaways"), 5),
        counterpoints=_safe_int(raw.get("counterpoints"), 3),
        key_concepts_count=_safe_int(raw.get("key_concepts_count"), 5),

        # AI model
        gemini_model=raw.get("gemini_model", "gemini-2.5-pro"),
        search_provider=raw.get("search_provider", "gemini"),

        # Output toggles
        enable_email=_safe_bool(raw.get("enable_email"), True),
        enable_pdf=_safe_bool(raw.get("enable_pdf"), True),
        enable_html=_safe_bool(raw.get("enable_html"), True),
        enable_markdown=_safe_bool(raw.get("enable_markdown"), True),

        # Email
        recipient_email=os.getenv("RECIPIENT_EMAIL") or raw.get("recipient_email", "user@example.com"),
        sender_email=os.getenv("SENDER_EMAIL") or raw.get("sender_email", "newsletter@yourdomain.com"),
        email_subject_prefix=raw.get("email_subject_prefix", "Daily Research Brief"),

        # File paths
        topics_file=raw.get("topics_file", "topics.xlsx"),
        output_dir=raw.get("output_dir", "output"),
        log_dir=raw.get("log_dir", "logs"),

        # Retry
        max_retries=_safe_int(raw.get("max_retries"), 3),
        retry_delay_seconds=_safe_int(raw.get("retry_delay_seconds"), 2),

        # Source tiers
        preferred_source_tiers=raw.get("preferred_source_tiers", {}),

        # Practitioner layer
        practitioner_layer_enabled=_safe_bool(
            raw.get("practitioner_layer_enabled"), True
        ),
        practitioner_topic_keywords=_safe_list(
            raw.get("practitioner_topic_keywords"),
            default_practitioner_keywords,
        ),

        # Article persona & style
        linkedin_post_persona=raw.get(
            "linkedin_post_persona", default_persona
        ),
        banned_phrases=_safe_list(
            raw.get("banned_phrases"), default_banned_phrases
        ),

        # Scheduler
        daily_run_time=raw.get("daily_run_time", "07:00"),
        pipeline_timeout_seconds=_safe_int(
            raw.get("pipeline_timeout_seconds"), 600
        ),

        # Cost tracking
        enable_cost_tracking=_safe_bool(raw.get("enable_cost_tracking"), True),

        # Testing mode
        testing_mode=_safe_bool(raw.get("testing_mode"), False),

        # API keys from environment only
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        resend_api_key=os.getenv("RESEND_API_KEY", ""),
    )

    _validate_config(config)
    return config


# ------------------------------------------------------------------
# Safe converters
# ------------------------------------------------------------------

def _safe_int(value: Any, default: int) -> int:
    """Safely convert a value to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_bool(value: Any, default: bool) -> bool:
    """Safely convert a value to bool, returning default on failure."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return default


def _safe_list(value: Any, default: list) -> list:
    """Safely return a list from YAML value, returning default if not a list."""
    if value is None:
        return default
    if isinstance(value, list):
        return [str(item) for item in value]
    return default


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------

_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")


def _validate_config(config: AppConfig) -> None:
    """
    Validate configuration values comprehensively.

    Raises:
        ValueError: If critical configuration is invalid.
    """
    errors: list[str] = []

    # --- Numeric range checks ---
    if not 100 <= config.article_words <= 10000:
        errors.append(
            f"article_words must be 100–10000, got {config.article_words}"
        )
    if not 50 <= config.executive_summary_words <= 1000:
        errors.append(
            f"executive_summary_words must be 50–1000, "
            f"got {config.executive_summary_words}"
        )
    if config.linkedin_angles < 1:
        errors.append(f"linkedin_angles must be >= 1, got {config.linkedin_angles}")
    if config.key_takeaways < 1:
        errors.append(f"key_takeaways must be >= 1, got {config.key_takeaways}")
    if config.counterpoints < 1:
        errors.append(f"counterpoints must be >= 1, got {config.counterpoints}")
    if config.key_concepts_count < 1:
        errors.append(
            f"key_concepts_count must be >= 1, got {config.key_concepts_count}"
        )
    if config.max_retries < 1:
        errors.append(f"max_retries must be >= 1, got {config.max_retries}")
    if config.retry_delay_seconds < 0:
        errors.append(
            f"retry_delay_seconds must be >= 0, got {config.retry_delay_seconds}"
        )
    if config.pipeline_timeout_seconds < 60:
        errors.append(
            f"pipeline_timeout_seconds must be >= 60, "
            f"got {config.pipeline_timeout_seconds}"
        )

    # --- API key checks ---
    if not config.gemini_api_key:
        errors.append(
            "GEMINI_API_KEY not set. Add it to your .env file or environment."
        )
    if config.enable_email and not config.resend_api_key:
        errors.append(
            "RESEND_API_KEY not set but enable_email is true. "
            "Set the key or set enable_email: false in config.yaml."
        )

    # --- Email format checks ---
    if config.enable_email:
        if not _EMAIL_PATTERN.match(config.recipient_email):
            errors.append(
                f"recipient_email is not a valid email: '{config.recipient_email}'"
            )
        if config.recipient_email == "user@example.com":
            logger.warning(
                "recipient_email is still the default 'user@example.com'. "
                "Update config.yaml with a real address."
            )

    # --- File path check ---
    if not Path(config.topics_file).suffix == ".xlsx":
        errors.append(
            f"topics_file must be an .xlsx file, got: {config.topics_file}"
        )

    # --- Scheduler time format ---
    if not _TIME_PATTERN.match(config.daily_run_time):
        errors.append(
            f"daily_run_time must be HH:MM format, got: '{config.daily_run_time}'"
        )
    else:
        hours, minutes = config.daily_run_time.split(":")
        if int(hours) > 23 or int(minutes) > 59:
            errors.append(
                f"daily_run_time is invalid: '{config.daily_run_time}'. "
                "Hours 00–23, minutes 00–59."
            )

    # --- Search provider ---
    valid_providers = {"gemini"}
    if config.search_provider not in valid_providers:
        errors.append(
            f"search_provider must be one of {valid_providers}, "
            f"got: '{config.search_provider}'"
        )

    if errors:
        error_msg = "Configuration errors:\n" + "\n".join(
            f"  - {e}" for e in errors
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    # --- Non-fatal warnings ---
    if config.testing_mode:
        logger.warning(
            "TESTING MODE enabled -- topics will NOT be marked as Done."
        )
    if not config.practitioner_layer_enabled:
        logger.info(
            "Practitioner layer disabled -- Layer 2 research will be skipped."
        )

    logger.info("Configuration validated successfully")