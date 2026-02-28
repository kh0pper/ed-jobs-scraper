"""Email sending service via Gmail SMTP."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    """Send an email via SMTP.

    Args:
        to: Recipient email address
        subject: Email subject
        html: HTML body
        text: Optional plain text alternative

    Returns:
        True on success, False on failure
    """
    settings = get_settings()

    if not settings.smtp_user or not settings.smtp_password:
        logger.error("SMTP not configured (missing smtp_user/smtp_password)")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_user
    msg["To"] = to
    msg["Subject"] = subject

    if text:
        msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

        logger.info("Email sent to %s: %s", to, subject)
        return True

    except Exception as e:
        logger.error("Failed to send email to %s: %s", to, e)
        return False
