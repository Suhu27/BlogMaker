"""
PDF generator for BlogMaker.

Converts rendered HTML to PDF using WeasyPrint.
Gracefully handles missing WeasyPrint installation.
"""

from src.logger import get_logger

logger = get_logger("pdf_generator")


def generate_pdf(html_content: str, output_path: str) -> bool:
    """
    Generate a PDF from HTML content using WeasyPrint.

    If WeasyPrint is not installed (missing system dependencies),
    logs a warning and returns False instead of crashing.

    Args:
        html_content: The full HTML string to convert.
        output_path: File path to save the PDF.

    Returns:
        True if PDF was generated successfully, False otherwise.
    """
    try:
        from weasyprint import HTML
    except ImportError as e:
        logger.warning(
            "WeasyPrint is not available: %s\n"
            "PDF generation skipped. To enable PDF output, install WeasyPrint:\n"
            "  pip install weasyprint\n"
            "  (Requires GTK3/Pango/Cairo system libraries on Windows)\n"
            "See README.md for detailed installation instructions.",
            str(e),
        )
        return False
    except OSError as e:
        logger.warning(
            "WeasyPrint system dependencies missing: %s\n"
            "PDF generation skipped. See README.md for setup instructions.",
            str(e),
        )
        return False

    try:
        logger.info("Generating PDF: %s", output_path)
        HTML(string=html_content).write_pdf(output_path)
        logger.info("PDF generated successfully: %s", output_path)
        return True
    except Exception as e:
        logger.error("PDF generation failed: %s", str(e))
        return False
