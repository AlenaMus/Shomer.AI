"""SmtpEmailSender — stdlib SMTP adapter for the Mailer module.

Uses ``smtplib`` + ``email.message.EmailMessage`` (stdlib only).  Runs the
blocking SMTP call inside ``asyncio.to_thread`` so the event loop is never
blocked.

Selected when ``MAILER_BACKEND=smtp``.

Transport:
  - STARTTLS on the configured port (default 587).
  - Login with ``SMTP_USERNAME`` / ``SMTP_PASSWORD``.
  - UTF-8 content type for Hebrew-safe subject + body.

Failure semantics:
  - Any exception during connect/auth/send is caught, logged as an error, and
    False is returned.  The caller treats this as best-effort; it MUST NOT raise.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

import structlog

from .settings import MailerSettings

log = structlog.get_logger("shomer.mailer.smtp")


class SmtpEmailSender:
    """SMTP-backed EmailSender (STARTTLS, asyncio-safe)."""

    def __init__(self, settings: MailerSettings) -> None:
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._username = settings.smtp_username
        self._password = settings.smtp_password
        self._from = settings.from_address

    def _send_sync(self, to: str, subject: str, body: str) -> bool:
        """Blocking SMTP send — called via asyncio.to_thread."""
        msg = EmailMessage()
        msg["From"] = self._from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body, charset="utf-8")

        try:
            with smtplib.SMTP(self._host, self._port, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(self._username, self._password)
                smtp.send_message(msg)
            domain = to.split("@", 1)[-1] if "@" in to else "unknown"
            log.info(
                "mailer.smtp_sent",
                recipient_domain=domain,
                subject=subject,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            domain = to.split("@", 1)[-1] if "@" in to else "unknown"
            log.error(
                "mailer.smtp_failed",
                recipient_domain=domain,
                subject=subject,
                error=str(exc),
            )
            return False

    async def send(self, to: str, subject: str, body: str) -> bool:
        """Send email via STARTTLS SMTP without blocking the event loop."""
        return await asyncio.to_thread(self._send_sync, to, subject, body)
