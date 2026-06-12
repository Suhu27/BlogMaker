"""Tests for models module -- Source domain normalization and dataclass behavior."""

import pytest
from src.models import Source, ReliabilityResult, DeliveryResult, RunReport, Article


class TestSourceDomainNormalization:
    """Issue 3: Verify Source strips subdomain prefixes correctly."""

    def test_www_stripped(self):
        s = Source(url="https://www.reuters.com/article/123", title="Test")
        assert s.domain == "reuters.com"

    def test_www2_stripped(self):
        s = Source(url="https://www2.deloitte.com/report", title="Test")
        assert s.domain == "deloitte.com"

    def test_news_subdomain_stripped(self):
        s = Source(url="https://news.bloomberg.com/article", title="Test")
        assert s.domain == "bloomberg.com"

    def test_insights_subdomain_stripped(self):
        s = Source(url="https://insights.mckinsey.com/report", title="Test")
        assert s.domain == "mckinsey.com"

    def test_compound_tld_preserved(self):
        s = Source(url="https://news.bbc.co.uk/article", title="Test")
        assert s.domain == "bbc.co.uk"

    def test_gov_uk_preserved(self):
        s = Source(url="https://www.gov.uk/policy", title="Test")
        assert s.domain == "gov.uk"

    def test_simple_domain_unchanged(self):
        s = Source(url="https://imf.org/data", title="Test")
        assert s.domain == "imf.org"

    def test_empty_url(self):
        s = Source(url="", title="Test")
        assert s.domain == ""

    def test_port_stripped(self):
        s = Source(url="https://localhost:8080/test", title="Test")
        # localhost doesn't have compound TLD, should normalize
        assert ":" not in s.domain

    def test_deep_subdomain(self):
        s = Source(url="https://research.papers.arxiv.org/123", title="Test")
        assert s.domain == "arxiv.org"


class TestDeliveryResult:
    """Issue 7: DeliveryResult serialization."""

    def test_success(self):
        dr = DeliveryResult(status="SUCCESS", email_id="abc123", attempts=1)
        d = dr.to_dict()
        assert d["delivery_status"] == "SUCCESS"
        assert d["email_id"] == "abc123"

    def test_failed(self):
        dr = DeliveryResult(status="FAILED", error="timeout", attempts=3)
        d = dr.to_dict()
        assert d["delivery_status"] == "FAILED"
        assert d["error"] == "timeout"

    def test_skipped(self):
        dr = DeliveryResult(status="SKIPPED")
        assert dr.to_dict()["delivery_status"] == "SKIPPED"


class TestArticleMetadata:
    """Article.to_metadata_dict() completeness."""

    def test_includes_cost_tracking(self):
        a = Article(topic="test", total_input_tokens=100, total_output_tokens=50)
        d = a.to_metadata_dict()
        assert d["cost_tracking"]["total_input_tokens"] == 100
        assert d["cost_tracking"]["total_output_tokens"] == 50

    def test_section_counts(self):
        a = Article(
            topic="test",
            takeaways=["a", "b", "c"],
            key_concepts=["x", "y"],
        )
        d = a.to_metadata_dict()
        assert d["sections"]["takeaways_count"] == 3
        assert d["sections"]["key_concepts_count"] == 2


class TestRunReport:
    def test_serialization(self):
        r = RunReport(topic="AI", success=True, execution_time_seconds=42.567)
        d = r.to_dict()
        assert d["topic"] == "AI"
        assert d["execution_time_seconds"] == 42.6
        assert d["success"] is True
