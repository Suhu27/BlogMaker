"""
Output manager for BlogMaker.

Handles creation of dated output directories, saving all generated content,
and validating that required outputs exist.
"""

import json
from datetime import datetime
from pathlib import Path

from src.config import AppConfig
from src.logger import get_logger
from src.models import Article, RunReport

logger = get_logger("output_manager")


class OutputManager:
    """Manages output directory structure and file saving."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.base_dir = Path(config.output_dir)

    def prepare_output_dir(self, date: datetime | None = None) -> Path:
        """Create the dated output directory."""
        if date is None:
            date = datetime.now()
        date_str = date.strftime("%Y-%m-%d")
        output_dir = self.base_dir / date_str
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Output directory prepared: %s", output_dir)
        return output_dir

    def save_all(
        self,
        article: Article,
        html_content: str,
        output_dir: Path,
        pdf_generated: bool = False,
        delivery_result: dict | None = None,
    ) -> dict[str, Path]:
        """
        Save all generated content to the output directory.

        Args:
            article: The fully populated Article dataclass.
            html_content: Rendered HTML string.
            output_dir: Path to the dated output directory.
            pdf_generated: Whether PDF was successfully generated.
            delivery_result: Email delivery result dict for metadata.

        Returns:
            Dictionary mapping output type to file path.
        """
        saved_files: dict[str, Path] = {}

        # Save HTML
        if self.config.enable_html:
            html_path = output_dir / "article.html"
            html_path.write_text(html_content, encoding="utf-8")
            saved_files["html"] = html_path
            logger.info("Saved HTML: %s", html_path)

        # Save Markdown
        if self.config.enable_markdown:
            md_path = output_dir / "article.md"
            from src.markdown_writer import write_markdown
            write_markdown(article, str(md_path))
            saved_files["markdown"] = md_path

        # Save sources.json (enhanced - Issue 14)
        sources_data = [
            {
                "url": s.url,
                "title": s.title,
                "domain": s.domain,
                "publisher": s.publisher,
                "publication_date": s.publication_date,
                "tier": s.tier,
                "reliability_score": s.reliability_score,
                "detected_category": s.detected_category,
            }
            for s in article.sources
        ]
        sources_path = output_dir / "sources.json"
        sources_path.write_text(
            json.dumps(sources_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        saved_files["sources"] = sources_path
        logger.info("Saved sources: %s (%d entries)", sources_path, len(sources_data))

        # Save metadata.json (enhanced - Issue 7)
        metadata = article.to_metadata_dict()
        metadata["output_files"] = {k: str(v) for k, v in saved_files.items()}
        metadata["pdf_generated"] = pdf_generated
        metadata["gemini_model"] = self.config.gemini_model
        if delivery_result:
            metadata["email_delivery"] = delivery_result

        metadata_path = output_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        saved_files["metadata"] = metadata_path
        logger.info("Saved metadata: %s", metadata_path)

        return saved_files

    def validate_outputs(
        self, output_dir: Path, pdf_generated: bool
    ) -> tuple[bool, list[str]]:
        """
        Validate that all required output files exist and are non-empty.

        Args:
            output_dir: Path to the output directory.
            pdf_generated: Whether PDF was expected.

        Returns:
            Tuple of (all_valid, list_of_warnings).
        """
        warnings: list[str] = []
        required: list[tuple[str, bool]] = [
            ("sources.json", True),
            ("metadata.json", True),
        ]
        if self.config.enable_html:
            required.append(("article.html", True))
        if self.config.enable_markdown:
            required.append(("article.md", True))
        if self.config.enable_pdf and pdf_generated:
            required.append(("article.pdf", True))

        for filename, is_required in required:
            fpath = output_dir / filename
            if not fpath.exists():
                msg = f"Missing output file: {filename}"
                if is_required:
                    warnings.append(msg)
                    logger.warning(msg)
            elif fpath.stat().st_size == 0:
                msg = f"Empty output file: {filename}"
                warnings.append(msg)
                logger.warning(msg)

        all_valid = len(warnings) == 0
        if all_valid:
            logger.info("All output files validated successfully")
        else:
            logger.warning("Output validation found %d issue(s)", len(warnings))

        return all_valid, warnings

    def save_run_report(self, report: RunReport, output_dir: Path) -> Path:
        """Save the post-run report as run_report.json."""
        report_path = output_dir / "run_report.json"
        report_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved run report: %s", report_path)
        return report_path
