"""Tests for reliability scorer -- domain matching and scoring logic."""

import pytest
from src.models import Source
from src.reliability_scorer import ReliabilityScorer


@pytest.fixture
def scorer():
    return ReliabilityScorer()


class TestDomainScoring:
    """Issue 3: Verify domains are correctly classified and scored."""

    def test_tier1_exact_match(self, scorer):
        sources = [Source(url="https://www.oecd.org/report", title="OECD")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 10.0
        assert sources[0].tier == 1

    def test_tier1_imf(self, scorer):
        sources = [Source(url="https://imf.org/data", title="IMF")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 10.0

    def test_tier1_worldbank(self, scorer):
        sources = [Source(url="https://data.worldbank.org/report", title="WB")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 10.0

    def test_tier2_reuters(self, scorer):
        sources = [Source(url="https://www.reuters.com/article", title="Reuters")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 9.0
        assert sources[0].tier == 1  # score 9 -> tier 1

    def test_tier2_bloomberg_subdomain(self, scorer):
        """Issue 3: news.bloomberg.com should match bloomberg.com."""
        sources = [Source(url="https://news.bloomberg.com/article", title="BBG")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 9.0

    def test_tier2_mckinsey_subdomain(self, scorer):
        """Issue 3: insights.mckinsey.com should match mckinsey.com."""
        sources = [Source(url="https://insights.mckinsey.com/report", title="McK")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 8.0
        assert sources[0].tier == 2

    def test_tier2_ft(self, scorer):
        sources = [Source(url="https://www.ft.com/article", title="FT")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 9.0

    def test_tier3_techcrunch(self, scorer):
        sources = [Source(url="https://techcrunch.com/article", title="TC")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 6.0
        assert sources[0].tier == 3

    def test_gov_domain(self, scorer):
        sources = [Source(url="https://data.treasury.gov/report", title="Gov")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 10.0

    def test_edu_domain(self, scorer):
        sources = [Source(url="https://cs.stanford.edu/paper", title="Stanford")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 10.0

    def test_unknown_domain_default(self, scorer):
        sources = [Source(url="https://randomsite.com/page", title="Random")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 5.0

    def test_org_domain_gets_7(self, scorer):
        """Unrecognized .org domains should get 7, not 5."""
        sources = [Source(url="https://somefoundation.org/report", title="Foundation")]
        result = scorer.calculate_reliability(sources)
        assert result.score == 7.0


class TestReliabilityAveraging:
    def test_mixed_sources(self, scorer):
        sources = [
            Source(url="https://reuters.com/a", title="Reuters"),       # 9
            Source(url="https://mckinsey.com/b", title="McKinsey"),     # 8
            Source(url="https://techcrunch.com/c", title="TechCrunch"), # 6
        ]
        result = scorer.calculate_reliability(sources)
        expected = round((9 + 8 + 6) / 3, 1)  # 7.7
        assert result.score == expected

    def test_empty_sources(self, scorer):
        result = scorer.calculate_reliability([])
        assert result.score == 0.0

    def test_source_details_populated(self, scorer):
        """Issue 14: source_details should include detected_category."""
        sources = [
            Source(url="https://reuters.com/a", title="Reuters"),
            Source(url="https://medium.com/b", title="Medium"),
        ]
        result = scorer.calculate_reliability(sources)
        assert len(result.source_details) == 2
        assert result.source_details[0]["detected_category"] != "Unknown"
        assert "domain" in result.source_details[0]
        assert "score" in result.source_details[0]


class TestCategoryDetection:
    def test_detected_category_set_on_source(self, scorer):
        sources = [Source(url="https://reuters.com/a", title="R")]
        scorer.calculate_reliability(sources)
        assert sources[0].detected_category != "Unknown"
        assert "Premium" in sources[0].detected_category
