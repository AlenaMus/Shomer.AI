"""LogEmailSender — structlog-backed EmailSender adapter.

The default adapter.  Every outbound email is logged at INFO level to the
structlog pipeline; no external dependency is required.  Returns True always.

Selected when ``MAILER_BACKEND=log`` (the default).

Useful for:
  - Local development (see the email in server.log without an SMTP server).
  - Integration tests (inject as ``app.state.mailer``; assert on log records
    or subclass to capture sends in a list).
  - CI/CD pipelines where email delivery is undesirable.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger("shomer.mailer.log")


class LogEmailSender:
    """Logs every email via structlog.  Always returns True (no I/O)."""

    async def send(self, to: str, subject: str, body: str) -> bool:
        # Log the domain of the recipient only — avoid PII in logs.
        domain = to.split("@", 1)[-1] if "@" in to else "unknown"
        log.info(
            "mailer.log_send",
            recipient_domain=domain,
            subject=subject,
            body_chars=len(body),
            body=body,  # full body intentional for dev-mode visibility
        )
        return True
