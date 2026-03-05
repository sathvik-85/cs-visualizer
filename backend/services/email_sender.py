import asyncio
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from config import settings

logger = logging.getLogger(__name__)


async def send_completion_email(to_email: str, topic: str, video_url: str) -> None:
    """Send a notification email when a video has finished rendering."""
    if not settings.smtp_host or not settings.smtp_user or not settings.smtp_password:
        logger.info("SMTP not configured — skipping email notification to %s", to_email)
        return

    subject = f"Your CS Visualizer video is ready: {topic[:60]}"
    body = f"""\
Hi there,

Your animation for "{topic}" has finished rendering!

Watch it here: {video_url}

(The link is only valid while the server is running.)

— CS Visualizer
"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))

    try:
        await asyncio.to_thread(_send_smtp, msg, to_email)
        logger.info("Notification email sent to %s", to_email)
    except Exception as exc:
        logger.warning("Failed to send notification email to %s: %s", to_email, exc)


def _send_smtp(msg: MIMEMultipart, to_email: str) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        server.ehlo()
        if settings.smtp_port != 465:
            server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(msg["From"], [to_email], msg.as_string())
