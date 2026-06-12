#!/usr/bin/env python3
"""
BlogMaker -- Daily AI Research Newsletter Generator

Usage:
    python main.py                          # Run pipeline once
    python main.py --config my_config.yaml  # Custom config file
    python main.py --topics my_topics.xlsx  # Custom topics file
    python main.py --dry-run                # Validate without API calls
    python main.py --schedule               # Run on daily schedule
    python main.py --create-example         # Create example topics.xlsx
"""

import argparse
import signal
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from src.config import AppConfig, load_config
from src.logger import setup_logging, get_logger
from src.models import RunReport


# Gemini 2.5 Pro pricing -- update if rates change
_GEMINI_INPUT_COST_PER_1M  = 1.25   # USD per 1M input tokens
_GEMINI_OUTPUT_COST_PER_1M = 10.00  # USD per 1M output tokens


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BlogMaker -- Daily AI Research Newsletter Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--topics", default=None, help="Override topics file path")
    parser.add_argument("--dry-run", action="store_true", help="Validate only")
    parser.add_argument("--create-example", action="store_true", help="Create topics.xlsx")
    parser.add_argument("--schedule", action="store_true", help="Run on daily schedule")
    return parser.parse_args()


# ============================================================
# DRY RUN
# ============================================================

def run_dry_run(config: AppConfig) -> None:
    logger = get_logger("dry_run")
    logger.info("=" * 60)
    logger.info("DRY RUN -- Validating pipeline structure")
    logger.info("=" * 60)

    logger.info("[OK] Configuration loaded and validated")
    logger.info("  Model: %s", config.gemini_model)
    logger.info("  Email enabled: %s", config.enable_email)
    logger.info("  PDF enabled: %s", config.enable_pdf)
    logger.info("  Testing mode: %s", config.testing_mode)

    from src.excel_handler import read_pending_topic
    topics_path = Path(config.topics_file)
    if topics_path.exists():
        topic_row = read_pending_topic(config.topics_file)
        if topic_row:
            logger.info(
                "[OK] Pending topic: '%s' (row %d)",
                topic_row.topic, topic_row.row_number,
            )
        else:
            logger.info("[WARN] No pending topics found")
    else:
        logger.warning("[WARN] Topics file not found: %s", config.topics_file)

    try:
        from src.search_providers import create_search_provider
        from src.researcher import GeminiResearcher, _topic_needs_practitioner_layer
        from src.article_generator import ArticleGenerator
        from src.reliability_scorer import ReliabilityScorer
        from src.html_renderer import render_html
        from src.pdf_generator import generate_pdf
        from src.markdown_writer import write_markdown
        from src.output_manager import OutputManager
        from src.email_sender import EmailSender
        logger.info("[OK] All modules imported successfully")
        logger.info(
            "[OK] Practitioner layer function reachable "
            "(test: 'job loss' -> %s)",
            _topic_needs_practitioner_layer("job loss due to AI"),
        )
    except ImportError as e:
        logger.error("[FAIL] Module import failed: %s", str(e))
        sys.exit(1)

    if Path("templates/newsletter.html").exists():
        logger.info("[OK] Newsletter template found")
    else:
        logger.warning("[WARN] Newsletter template missing")

    from src.output_manager import OutputManager
    om = OutputManager(config)
    test_dir = om.prepare_output_dir()
    logger.info("[OK] Output directory: %s", test_dir)

    logger.info("[%s] GEMINI_API_KEY", "OK" if config.gemini_api_key else "WARN")
    logger.info("[%s] RESEND_API_KEY", "OK" if config.resend_api_key else "WARN")

    logger.info("=" * 60)
    logger.info("DRY RUN COMPLETE -- Pipeline structure is valid")
    logger.info("=" * 60)


# ============================================================
# MAIN PIPELINE
# ============================================================

def run_pipeline(config: AppConfig) -> None:
    logger = get_logger("pipeline")
    start_time = time.time()
    report = RunReport()
    warnings: list[str] = []

    logger.info("=" * 60)
    logger.info("BlogMaker -- Starting newsletter generation pipeline")
    if config.testing_mode:
        logger.info("*** TESTING MODE -- Excel will NOT be modified ***")
    logger.info("=" * 60)

    # --- Step 1: Read pending topic ---
    logger.info("Step 1/9: Reading pending topic from Excel...")
    from src.excel_handler import read_pending_topic, mark_topic_done

    topic_row = read_pending_topic(config.topics_file)
    if topic_row is None:
        logger.info("No pending topics found. Nothing to process.")
        return

    topic = topic_row.topic
    report.topic = topic
    logger.info("Processing: '%s' (Priority: %s)", topic, topic_row.priority)

    # --- Step 2: Research topic ---
    logger.info("Step 2/9: Researching topic with Gemini...")
    from src.search_providers import create_search_provider

    provider = create_search_provider(config)
    research_text, sources = provider.search(topic)
    logger.info("Research complete -- %d sources found", len(sources))

    # --- Step 3: Generate article ---
    logger.info("Step 3/9: Generating structured article...")
    from src.article_generator import ArticleGenerator

    generator = ArticleGenerator(config)
    article = generator.generate_article(topic, research_text, sources)
    report.title = article.title
    report.article_word_count = len(article.main_content.split())
    logger.info("Article: '%s' (%d words)", article.title, report.article_word_count)

    # --- Step 4: Calculate reliability score ---
    logger.info("Step 4/9: Calculating reliability score...")
    from src.reliability_scorer import ReliabilityScorer

    scorer = ReliabilityScorer()
    article.reliability = scorer.calculate_reliability(article.sources)
    report.reliability_score = article.reliability.score
    report.source_count = len(article.sources)
    logger.info("Reliability score: %.1f/10", article.reliability.score)

    # --- Step 5: Render HTML ---
    logger.info("Step 5/9: Rendering HTML newsletter...")
    from src.html_renderer import render_html
    html_content = render_html(article, config)

    # --- Step 6: Prepare output directory ---
    logger.info("Step 6/9: Preparing output directory...")
    from src.output_manager import OutputManager

    output_mgr = OutputManager(config)
    output_dir = output_mgr.prepare_output_dir()
    report.output_dir = str(output_dir)

    # --- Step 7: Generate PDF ---
    pdf_generated = False
    pdf_path = str(output_dir / "article.pdf")
    if config.enable_pdf:
        logger.info("Step 7/9: Generating PDF...")
        from src.pdf_generator import generate_pdf
        pdf_generated = generate_pdf(html_content, pdf_path)
        if not pdf_generated:
            warnings.append("PDF generation failed or WeasyPrint unavailable")
    else:
        logger.info("Step 7/9: PDF disabled -- skipping")

    # --- Step 8: Send email ---
    from src.email_sender import EmailSender
    delivery_result = None
    if config.enable_email:
        logger.info("Step 8/9: Sending newsletter email...")
        sender = EmailSender(config)
        subject = f"{config.email_subject_prefix}: {article.title}"
        delivery = sender.send_newsletter(
            subject=subject,
            html_content=html_content,
            pdf_path=pdf_path if pdf_generated else None,
        )
        delivery_result = delivery.to_dict()
        report.email_status = delivery.status
        if delivery.status == "FAILED":
            warnings.append(f"Email delivery failed: {delivery.error}")
    else:
        logger.info("Step 8/9: Email disabled -- skipping")
        report.email_status = "SKIPPED"

    # --- Step 9: Save all outputs ---
    logger.info("Step 9/9: Saving all outputs...")

    # Cost tracking
    article.total_input_tokens  = provider.input_tokens + generator.input_tokens
    article.total_output_tokens = provider.output_tokens + generator.output_tokens
    report.total_input_tokens  = article.total_input_tokens
    report.total_output_tokens = article.total_output_tokens

    saved_files = output_mgr.save_all(
        article=article,
        html_content=html_content,
        output_dir=output_dir,
        pdf_generated=pdf_generated,
        delivery_result=delivery_result,
    )

    # Output validation
    outputs_valid, validation_warnings = output_mgr.validate_outputs(
        output_dir, pdf_generated
    )
    warnings.extend(validation_warnings)

    # --- Mark topic as Done ---
    can_mark_done = True

    if config.testing_mode:
        can_mark_done = False
        logger.info("Testing mode -- topic will NOT be marked as Done")

    elif config.enable_email and report.email_status == "FAILED":
        can_mark_done = False
        logger.warning(
            "Email delivery FAILED -- topic remains Pending to prevent data loss. "
            "Generated outputs preserved in: %s", output_dir,
        )

    elif not outputs_valid:
        can_mark_done = False
        logger.warning("Output validation failed -- topic remains Pending")

    if can_mark_done:
        mark_topic_done(config.topics_file, topic_row.row_number)
        logger.info("Topic marked as Done in Excel")

    # --- Save run report ---
    report.success = can_mark_done or config.testing_mode
    report.warnings = warnings
    report.output_paths = {k: str(v) for k, v in saved_files.items()}
    report.execution_time_seconds = time.time() - start_time
    output_mgr.save_run_report(report, output_dir)

    # --- Summary ---
    elapsed = report.execution_time_seconds
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("  Topic:       %s", topic)
    logger.info("  Title:       %s", article.title)
    logger.info("  Words:       %d (target: %d)", report.article_word_count, config.article_words)
    logger.info("  Sources:     %d", report.source_count)
    logger.info("  Reliability: %.1f/10", report.reliability_score)
    logger.info("  Output:      %s", output_dir)
    logger.info("  Email:       %s", report.email_status)
    logger.info("  Marked Done: %s", "Yes" if can_mark_done else "No")
    if config.enable_cost_tracking:
        est_cost = (
            report.total_input_tokens  / 1_000_000 * _GEMINI_INPUT_COST_PER_1M +
            report.total_output_tokens / 1_000_000 * _GEMINI_OUTPUT_COST_PER_1M
        )
        logger.info(
            "  Tokens:      %d in / %d out  (est. $%.4f)",
            report.total_input_tokens,
            report.total_output_tokens,
            est_cost,
        )
    if warnings:
        logger.info("  Warnings: %d", len(warnings))
        for w in warnings:
            logger.info("    - %s", w)
    logger.info("  Time:        %.1f seconds", elapsed)
    logger.info("=" * 60)


# ============================================================
# SCHEDULER
# ============================================================

_shutdown_requested = False
_PIPELINE_TIMEOUT_SECONDS = 600  # 10 minutes -- adjust if topics are complex


def _signal_handler(signum, frame) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def _run_pipeline_with_timeout(config: AppConfig, timeout: int) -> None:
    """
    Run the pipeline in a daemon thread with a hard timeout.

    Raises RuntimeError if the pipeline does not complete within
    `timeout` seconds -- protects the scheduler from a silent hang
    caused by a Gemini API stall.
    """
    error: list[Exception] = []

    def target() -> None:
        try:
            run_pipeline(config)
        except Exception as e:
            error.append(e)

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        raise RuntimeError(
            f"Pipeline timed out after {timeout}s -- "
            "Gemini API may be stalled. Topic NOT marked as Done."
        )
    if error:
        raise error[0]


def run_scheduler(config: AppConfig) -> None:
    """Run the pipeline on a daily schedule."""
    logger = get_logger("scheduler")
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    hours, minutes = config.daily_run_time.split(":")
    target_hour, target_minute = int(hours), int(minutes)

    logger.info("=" * 60)
    logger.info("BlogMaker SCHEDULER started")
    logger.info("  Daily run time: %s", config.daily_run_time)
    logger.info("  Pipeline timeout: %ds", _PIPELINE_TIMEOUT_SECONDS)
    logger.info("  Press Ctrl+C to stop")
    logger.info("=" * 60)

    while not _shutdown_requested:
        now = datetime.now()
        target = now.replace(
            hour=target_hour, minute=target_minute, second=0, microsecond=0
        )

        if target <= now:
            target += timedelta(days=1)

        wait_seconds = (target - now).total_seconds()
        logger.info(
            "Next run: %s (in %.0f minutes)",
            target.strftime("%Y-%m-%d %H:%M"),
            wait_seconds / 60,
        )

        # Wait in small increments for clean Ctrl+C handling
        while wait_seconds > 0 and not _shutdown_requested:
            sleep_time = min(wait_seconds, 30)
            time.sleep(sleep_time)
            wait_seconds -= sleep_time

        if _shutdown_requested:
            break

        logger.info(
            "Scheduled run triggered at %s",
            datetime.now().strftime("%H:%M"),
        )
        try:
            _run_pipeline_with_timeout(config, _PIPELINE_TIMEOUT_SECONDS)
        except Exception as e:
            logger.error("Scheduled run failed: %s", str(e))

    logger.info("Scheduler stopped cleanly")


# ============================================================
# ENTRY POINT
# ============================================================

def main() -> None:
    args = parse_args()

    if args.create_example:
        from src.excel_handler import create_example_xlsx
        setup_logging()
        create_example_xlsx("topics.xlsx")
        print("Created example topics.xlsx")
        return

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.topics:
        config.topics_file = args.topics

    setup_logging(config.log_dir)
    logger = get_logger("main")

    try:
        if args.dry_run:
            run_dry_run(config)
        elif args.schedule:
            run_scheduler(config)
        else:
            run_pipeline(config)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except FileNotFoundError as e:
        logger.error("File not found: %s", str(e))
        sys.exit(1)
    except ValueError as e:
        logger.error("Invalid value: %s", str(e))
        sys.exit(1)
    except RuntimeError as e:
        logger.error("Pipeline error: %s", str(e))
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error: %s", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()