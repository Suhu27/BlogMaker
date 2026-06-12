"""
Markdown writer for BlogMaker.

Converts an Article dataclass into clean, structured Markdown.
"""

from pathlib import Path

from src.logger import get_logger
from src.models import Article

logger = get_logger("markdown_writer")


def write_markdown(article: Article, output_path: str) -> None:
    """
    Write the article as a Markdown file.

    Produces a clean, readable Markdown document with all sections,
    proper heading hierarchy, and numbered source references.

    Args:
        article: The fully populated Article dataclass.
        output_path: File path to save the .md file.
    """
    lines: list[str] = []

    # Title
    lines.append(f"# {article.title}")
    lines.append("")
    lines.append(f"*Generated: {article.generated_at}*")
    lines.append(f"*Topic: {article.topic}*")
    lines.append("")

    # Executive Summary
    lines.append("---")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(article.executive_summary)
    lines.append("")

    # Main Article
    lines.append("---")
    lines.append("")
    lines.append("## In-Depth Analysis")
    lines.append("")
    lines.append(article.main_content)
    lines.append("")

    # Key Concepts
    if article.key_concepts:
        lines.append("---")
        lines.append("")
        lines.append("## Key Concepts")
        lines.append("")
        for i, concept in enumerate(article.key_concepts, 1):
            lines.append(f"{i}. {concept}")
        lines.append("")

    # Industry Impact
    if article.industry_impact:
        lines.append("---")
        lines.append("")
        lines.append("## Industry Impact")
        lines.append("")
        lines.append(article.industry_impact)
        lines.append("")

    # Career & Job Implications
    if article.career_implications:
        lines.append("---")
        lines.append("")
        lines.append("## Career & Job Implications")
        lines.append("")
        lines.append(article.career_implications)
        lines.append("")

    # Counterpoints
    if article.counterpoints:
        lines.append("---")
        lines.append("")
        lines.append("## Counterpoints")
        lines.append("")
        for cp in article.counterpoints:
            lines.append(f"- {cp}")
        lines.append("")

    # Key Takeaways
    if article.takeaways:
        lines.append("---")
        lines.append("")
        lines.append("## Key Takeaways")
        lines.append("")
        for i, takeaway in enumerate(article.takeaways, 1):
            lines.append(f"{i}. {takeaway}")
        lines.append("")

    # LinkedIn Content Ideas
    if article.linkedin_ideas:
        lines.append("---")
        lines.append("")
        lines.append("## LinkedIn Content Ideas")
        lines.append("")
        for i, idea in enumerate(article.linkedin_ideas, 1):
            lines.append(f"{i}. {idea}")
        lines.append("")

    # Topic Refinement
    if article.topic_refinement:
        lines.append("---")
        lines.append("")
        lines.append("## Possible Topic Refinement")
        lines.append("")
        lines.append(f"*{article.topic_refinement}*")
        lines.append("")

    # Sources and Citations
    if article.sources:
        lines.append("---")
        lines.append("")
        lines.append("## Sources & Citations")
        lines.append("")
        for i, source in enumerate(article.sources, 1):
            title = source.title or source.domain or source.url
            lines.append(f"{i}. [{title}]({source.url})")
        lines.append("")

    # Write to file
    md_content = "\n".join(lines)
    Path(output_path).write_text(md_content, encoding="utf-8")

    logger.info("Markdown written: %s (%d lines)", output_path, len(lines))
