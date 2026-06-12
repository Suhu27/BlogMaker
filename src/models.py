"""
Data models for BlogMaker.

Defines the core dataclasses used throughout the application:
Article, Source, TopicRow, ReliabilityResult, DeliveryResult, RunReport.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Source:
    """A single research source extracted from Gemini grounding metadata."""

    url: str
    title: str
    domain: str = ""
    publisher: str = ""
    publication_date: str = ""
    tier: int = 3  # 1 = academic/gov, 2 = premium news/consulting, 3 = tech/blog
    reliability_score: float = 5.0
    detected_category: str = "Unknown"

    def __post_init__(self) -> None:
        """Extract and normalize domain from URL."""
        if not self.domain and self.url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(self.url)
                raw_domain = parsed.netloc.lower()
                self.domain = self._normalize_domain(raw_domain)
            except Exception:
                self.domain = ""

    @staticmethod
    def _normalize_domain(raw: str) -> str:
        """
        Strip common subdomain prefixes to get the registrable domain.

        Handles: www., www2., www3., news., blog., blogs., m., mobile.,
        en., app., apps., static., cdn., api., docs., support., help., etc.

        For co.uk / gov.uk / com.au style TLDs, preserves the two-part suffix.
        """
        if not raw:
            return ""

        # Remove port number if present
        raw = raw.split(":")[0]

        # Known compound TLDs (preserve these as suffixes)
        compound_tlds = {
            "co.uk", "gov.uk", "ac.uk", "org.uk", "com.au", "co.jp",
            "co.in", "com.br", "co.za", "gov.au", "gov.in",
        }

        parts = raw.split(".")
        if len(parts) <= 2:
            return raw

        # Check if last two parts form a compound TLD
        last_two = ".".join(parts[-2:])
        if last_two in compound_tlds:
            if len(parts) == 3:
                # e.g., www.gov.uk -> gov.uk or bbc.co.uk -> bbc.co.uk
                # If the prefix is just www/www2, drop it
                _strip_prefixes = {"www", "www2", "www3", "m", "mobile"}
                if parts[0] in _strip_prefixes:
                    return last_two
                return raw  # e.g., bbc.co.uk stays as-is
            if len(parts) > 3:
                # e.g., news.bbc.co.uk -> bbc.co.uk
                return ".".join(parts[-3:])
            return raw

        # Standard domain: keep last 2 parts (e.g., bloomberg.com from news.bloomberg.com)
        return ".".join(parts[-2:])


@dataclass
class ReliabilityResult:
    """Result of rule-based reliability scoring."""

    score: float  # 0-10
    explanation: str
    source_breakdown: dict[str, list[str]] = field(default_factory=dict)
    source_details: list[dict] = field(default_factory=list)
    # Per-source detail: [{"url": ..., "domain": ..., "score": ..., "category": ...}]


@dataclass
class TopicRow:
    """A single topic row from the Excel spreadsheet."""

    topic: str
    status: str
    priority: str
    row_number: int  # 1-indexed row in Excel for update


@dataclass
class DeliveryResult:
    """Result of email delivery attempt."""

    status: str  # "SUCCESS", "FAILED", "SKIPPED"
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    error: str = ""
    email_id: str = ""
    attempts: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "delivery_status": self.status,
            "timestamp": self.timestamp,
            "error": self.error,
            "email_id": self.email_id,
            "attempts": self.attempts,
        }


@dataclass
class Article:
    """A fully generated newsletter article."""

    # Metadata
    topic: str
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Content sections
    title: str = ""
    executive_summary: str = ""
    main_content: str = ""
    key_concepts: list[str] = field(default_factory=list)
    industry_impact: str = ""
    career_implications: str = ""
    counterpoints: list[str] = field(default_factory=list)
    takeaways: list[str] = field(default_factory=list)
    linkedin_ideas: list[str] = field(default_factory=list)
    topic_refinement: str = ""

    # Sources and scoring
    sources: list[Source] = field(default_factory=list)
    reliability: ReliabilityResult | None = None

    # Cost tracking
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    def to_metadata_dict(self) -> dict:
        """Convert article metadata to a dictionary for JSON export."""
        return {
            "topic": self.topic,
            "title": self.title,
            "generated_at": self.generated_at,
            "source_count": len(self.sources),
            "reliability_score": self.reliability.score if self.reliability else 0,
            "sections": {
                "executive_summary_length": len(self.executive_summary.split()),
                "main_content_length": len(self.main_content.split()),
                "key_concepts_count": len(self.key_concepts),
                "counterpoints_count": len(self.counterpoints),
                "takeaways_count": len(self.takeaways),
                "linkedin_ideas_count": len(self.linkedin_ideas),
            },
            "cost_tracking": {
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
            },
        }


@dataclass
class RunReport:
    """Post-run execution report saved as run_report.json."""

    topic: str = ""
    title: str = ""
    success: bool = False
    execution_time_seconds: float = 0.0
    source_count: int = 0
    reliability_score: float = 0.0
    article_word_count: int = 0
    email_status: str = "SKIPPED"
    output_dir: str = ""
    output_paths: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "topic": self.topic,
            "title": self.title,
            "success": self.success,
            "execution_time_seconds": round(self.execution_time_seconds, 1),
            "source_count": self.source_count,
            "reliability_score": self.reliability_score,
            "article_word_count": self.article_word_count,
            "email_status": self.email_status,
            "output_dir": self.output_dir,
            "output_paths": self.output_paths,
            "warnings": self.warnings,
            "cost_tracking": {
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
            },
            "generated_at": self.generated_at,
        }
