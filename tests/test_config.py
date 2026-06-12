"""Tests for config validation."""

import os
import pytest
import tempfile
import yaml
from src.config import load_config, _validate_config, AppConfig


@pytest.fixture
def valid_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_API_KEY", "test-resend-key")


def _write_config(tmp_path, overrides=None):
    """Write a config.yaml with defaults + overrides."""
    config = {
        "article_words": 1500,
        "executive_summary_words": 150,
        "linkedin_angles": 3,
        "key_takeaways": 5,
        "counterpoints": 3,
        "key_concepts_count": 5,
        "gemini_model": "gemini-2.5-pro",
        "search_provider": "gemini",
        "enable_email": True,
        "enable_pdf": True,
        "enable_html": True,
        "enable_markdown": True,
        "recipient_email": "test@example.com",
        "sender_email": "sender@example.com",
        "topics_file": "topics.xlsx",
        "daily_run_time": "07:00",
        "testing_mode": False,
    }
    if overrides:
        config.update(overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(config))
    return str(path)


class TestConfigValidation:
    def test_valid_config_loads(self, tmp_path, valid_env):
        path = _write_config(tmp_path)
        config = load_config(path)
        assert config.article_words == 1500

    def test_article_words_too_low(self, tmp_path, valid_env):
        path = _write_config(tmp_path, {"article_words": 50})
        with pytest.raises(ValueError, match="article_words"):
            load_config(path)

    def test_article_words_too_high(self, tmp_path, valid_env):
        path = _write_config(tmp_path, {"article_words": 20000})
        with pytest.raises(ValueError, match="article_words"):
            load_config(path)

    def test_missing_gemini_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("RESEND_API_KEY", "key")
        # Prevent dotenv from loading real .env
        monkeypatch.setattr("src.config.load_dotenv", lambda: None)
        path = _write_config(tmp_path)
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            load_config(path)

    def test_email_enabled_no_resend_key(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "key")
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.setattr("src.config.load_dotenv", lambda: None)
        path = _write_config(tmp_path, {"enable_email": True})
        with pytest.raises(ValueError, match="RESEND_API_KEY"):
            load_config(path)

    def test_invalid_email_format(self, tmp_path, valid_env):
        path = _write_config(tmp_path, {"recipient_email": "not-an-email"})
        with pytest.raises(ValueError, match="recipient_email"):
            load_config(path)

    def test_invalid_daily_run_time(self, tmp_path, valid_env):
        path = _write_config(tmp_path, {"daily_run_time": "25:00"})
        with pytest.raises(ValueError, match="daily_run_time"):
            load_config(path)

    def test_invalid_time_format(self, tmp_path, valid_env):
        path = _write_config(tmp_path, {"daily_run_time": "7am"})
        with pytest.raises(ValueError, match="daily_run_time"):
            load_config(path)

    def test_invalid_search_provider(self, tmp_path, valid_env):
        path = _write_config(tmp_path, {"search_provider": "bing"})
        with pytest.raises(ValueError, match="search_provider"):
            load_config(path)

    def test_testing_mode_flag(self, tmp_path, valid_env):
        path = _write_config(tmp_path, {"testing_mode": True})
        config = load_config(path)
        assert config.testing_mode is True

    def test_boolean_string_conversion(self, tmp_path, valid_env):
        path = _write_config(tmp_path, {"enable_pdf": "false"})
        config = load_config(path)
        assert config.enable_pdf is False

    def test_missing_config_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent.yaml")
