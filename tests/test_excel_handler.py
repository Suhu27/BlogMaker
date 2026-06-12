"""Tests for Excel handler -- read, write, and edge cases."""

import pytest
from pathlib import Path
from src.excel_handler import read_pending_topic, mark_topic_done, create_example_xlsx


@pytest.fixture
def sample_xlsx(tmp_path):
    """Create a sample topics.xlsx in a temp dir."""
    filepath = str(tmp_path / "topics.xlsx")
    create_example_xlsx(filepath)
    return filepath


class TestReadPendingTopic:
    def test_reads_first_pending(self, sample_xlsx):
        topic = read_pending_topic(sample_xlsx)
        assert topic is not None
        assert topic.topic == "Banking with AI"
        assert topic.status == "Pending"
        assert topic.row_number == 2

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            read_pending_topic("nonexistent.xlsx")

    def test_all_done_returns_none(self, sample_xlsx):
        # Mark all topics as done
        for row in range(2, 7):
            mark_topic_done(sample_xlsx, row)
        topic = read_pending_topic(sample_xlsx)
        assert topic is None


class TestMarkTopicDone:
    def test_marks_done(self, sample_xlsx):
        topic = read_pending_topic(sample_xlsx)
        assert topic is not None
        mark_topic_done(sample_xlsx, topic.row_number)

        # Next pending should be different
        next_topic = read_pending_topic(sample_xlsx)
        assert next_topic is not None
        assert next_topic.topic != "Banking with AI"
        assert next_topic.topic == "Future of Jobs"

    def test_invalid_row_raises(self, sample_xlsx):
        with pytest.raises(ValueError):
            mark_topic_done(sample_xlsx, 999)

    def test_sequential_processing(self, sample_xlsx):
        """Process all 5 topics in order."""
        expected = [
            "Banking with AI", "Future of Jobs",
            "Quantum Computing in Finance", "Green Energy Policy 2025",
            "Cybersecurity Trends",
        ]
        for name in expected:
            topic = read_pending_topic(sample_xlsx)
            assert topic is not None
            assert topic.topic == name
            mark_topic_done(sample_xlsx, topic.row_number)

        # All done
        assert read_pending_topic(sample_xlsx) is None


class TestTestingMode:
    """Issue 8: Verify testing mode doesn't modify Excel (tested at pipeline level)."""

    def test_not_marking_preserves_topic(self, sample_xlsx):
        """If we read but don't mark, topic stays pending."""
        topic1 = read_pending_topic(sample_xlsx)
        topic2 = read_pending_topic(sample_xlsx)
        assert topic1.topic == topic2.topic
        assert topic1.row_number == topic2.row_number
