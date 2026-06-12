"""
HTML renderer for BlogMaker.

Renders the newsletter HTML using Jinja2 templates.
"""

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
import markdown

from src.config import AppConfig
from src.logger import get_logger
from src.models import Article

logger = get_logger("html_renderer")


def render_html(article: Article, config: AppConfig) -> str:
    """
    Render the newsletter HTML from the Jinja2 template.

    Args:
        article: The fully populated Article dataclass.
        config: Application configuration.

    Returns:
        Rendered HTML string.

    Raises:
        FileNotFoundError: If the template file is not found.
    """
    # Locate template directory
    template_dir = Path(__file__).parent.parent / "templates"
    if not template_dir.exists():
        raise FileNotFoundError(
            f"Templates directory not found: {template_dir}\n"
            "Ensure the 'templates/' folder exists with newsletter.html"
        )

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=False,  # We control HTML output in the template
    )

    template = env.get_template("newsletter.html")

    today = datetime.now().strftime("%B %d, %Y")
    
    # Convert markdown fields to HTML
    md = markdown.Markdown(extensions=['extra', 'nl2br'])
    main_content_html = md.convert(article.main_content)

    html = template.render(
        article=article,
        main_content_html=main_content_html,
        config=config,
        date=today,
    )

    logger.info("HTML newsletter rendered (%d characters)", len(html))
    return html
