"""
Email sender for BlogMaker.

Sends the newsletter via Resend API with HTML body and PDF attachment.
Returns a DeliveryResult with status, error details, and timestamps.
"""

import base64
import time
from pathlib import Path

import resend

from src.config import AppConfig
from src.logger import get_logger
from src.models import DeliveryResult

logger = get_logger("email_sender")


class EmailSender:
    """Sends newsletters via Resend API."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        resend.api_key = config.resend_api_key
        logger.info("Email sender initialized")

    def send_newsletter(
        self,
        subject: str,
        html_content: str,
        pdf_path: str | None = None,
    ) -> DeliveryResult:
        """
        Send the newsletter email with optional PDF attachment.

        Returns:
            DeliveryResult with status, error, timestamp, and email_id.
        """
        if not self.config.enable_email:
            logger.info("Email delivery disabled in config -- skipping")
            return DeliveryResult(status="SKIPPED")

        if not self.config.resend_api_key:
            logger.error("RESEND_API_KEY not set -- cannot send email")
            return DeliveryResult(status="FAILED", error="RESEND_API_KEY not set")

        # Build email parameters
        params: dict = {
            "from": self.config.sender_email,
            "to": [self.config.recipient_email],
            "subject": subject,
            "html": html_content,
        }

        # Attach PDF if available
        if pdf_path and Path(pdf_path).exists():
            try:
                with open(pdf_path, "rb") as f:
                    pdf_content = base64.b64encode(f.read()).decode("utf-8")
                params["attachments"] = [
                    {"content": pdf_content, "filename": Path(pdf_path).name}
                ]
                logger.info("PDF attached: %s", pdf_path)
            except Exception as e:
                logger.warning("Failed to attach PDF: %s (sending without)", str(e))

        # Send with retry logic
        return self._send_with_retry(params)

    def _send_with_retry(self, params: dict) -> DeliveryResult:
        """Send email with exponential backoff retry."""
        last_error = ""

        for attempt in range(1, self.config.max_retries + 1):
            try:
                logger.info(
                    "Sending email to %s (attempt %d/%d)...",
                    self.config.recipient_email, attempt, self.config.max_retries,
                )
                result = resend.Emails.send(params)
                email_id = ""
                if isinstance(result, dict):
                    email_id = result.get("id", "")
                else:
                    email_id = str(getattr(result, "id", ""))

                logger.info("Email sent successfully! ID: %s", email_id)
                return DeliveryResult(
                    status="SUCCESS", email_id=email_id, attempts=attempt,
                )

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Email send failed (attempt %d/%d): %s",
                    attempt, self.config.max_retries, last_error,
                )
                if attempt < self.config.max_retries:
                    delay = self.config.retry_delay_seconds * (2 ** (attempt - 1))
                    logger.info("Retrying in %d seconds...", delay)
                    time.sleep(delay)

        logger.error(
            "Email delivery failed after %d attempts. Last error: %s",
            self.config.max_retries, last_error,
        )
        return DeliveryResult(
            status="FAILED",
            error=last_error,
            attempts=self.config.max_retries,
        )
