"""Tests for output manager -- validation and report saving."""

import json
import pytest
from pathlib import Path
from src.config import AppConfig
from src.models import Article, RunReport, Source
from src.output_manager import OutputManager


@pytest.fixture
def config():
    return AppConfig(
        enable_html=True, enable_markdown=True, enable_pdf=True,
        output_dir="test_output", gemini_api_key="test", resend_api_key="test",
    )


@pytest.fixture
def output_dir(tmp_path):
    d = tmp_path / "output" / "2026-01-01"
    d.mkdir(parents=True)
    return d


class TestOutputValidation:
    """Issue 6: Validate outputs exist before marking success."""

    def test_all_files_present(self, config, output_dir):
        om = OutputManager(config)
        # Create all expected files
        (output_dir / "article.html").write_text("<html></html>")
        (output_dir / "article.md").write_text("# Test")
        (output_dir / "article.pdf").write_bytes(b"fake pdf")
        (output_dir / "sources.json").write_text("[]")
        (output_dir / "metadata.json").write_text("{}")

        valid, warnings = om.validate_outputs(output_dir, pdf_generated=True)
        assert valid is True
        assert len(warnings) == 0

    def test_missing_html(self, config, output_dir):
        om = OutputManager(config)
        (output_dir / "article.md").write_text("# Test")
        (output_dir / "sources.json").write_text("[]")
        (output_dir / "metadata.json").write_text("{}")

        valid, warnings = om.validate_outputs(output_dir, pdf_generated=False)
        assert valid is False
        assert any("article.html" in w for w in warnings)

    def test_empty_file_detected(self, config, output_dir):
        om = OutputManager(config)
        (output_dir / "article.html").write_text("<html></html>")
        (output_dir / "article.md").write_text("")  # Empty!
        (output_dir / "sources.json").write_text("[]")
        (output_dir / "metadata.json").write_text("{}")

        valid, warnings = om.validate_outputs(output_dir, pdf_generated=False)
        assert valid is False
        assert any("Empty" in w for w in warnings)

    def test_pdf_not_required_when_disabled(self, output_dir):
        config = AppConfig(
            enable_html=True, enable_markdown=False, enable_pdf=False,
            output_dir="test", gemini_api_key="t", resend_api_key="t",
        )
        om = OutputManager(config)
        (output_dir / "article.html").write_text("<html></html>")
        (output_dir / "sources.json").write_text("[]")
        (output_dir / "metadata.json").write_text("{}")

        valid, warnings = om.validate_outputs(output_dir, pdf_generated=False)
        assert valid is True


class TestRunReport:
    """Issue 9: Post-run report generation."""

    def test_saves_report(self, config, output_dir):
        om = OutputManager(config)
        report = RunReport(
            topic="AI in Banking",
            title="Test Article",
            success=True,
            execution_time_seconds=42.5,
            source_count=10,
            reliability_score=8.5,
            article_word_count=1500,
            email_status="SUCCESS",
        )
        path = om.save_run_report(report, output_dir)
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["topic"] == "AI in Banking"
        assert data["success"] is True
        assert data["execution_time_seconds"] == 42.5
        assert data["email_status"] == "SUCCESS"
