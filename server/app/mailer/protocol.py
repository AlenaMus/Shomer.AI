"""Public port for the Mailer module.

Handles transactional email sending (pairing-code OTPs, future notifications).

Concrete adapters:
  ``LogEmailSender``  — structlog-logs every outbound email; always returns True.
                        DEFAULT adapter; zero external deps.
  ``SmtpEmailSender`` — STARTTLS SMTP via stdlib; runs in a thread so the async
                        loop is never blocked.  Selected when MAILER_BACKEND=smtp.

Design constraints:
  - ``send`` is fire-and-forget-safe: callers MAY await it but MUST also handle
    send() returning False without crashing (e.g. log a warning and continue).
  - Email addresses passed to ``send`` are never logged in full — only the
    domain part is permissible in log lines.
  - This module is named ``mailer`` (not ``email``) to avoid shadowing the stdlib
    ``email`` package.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmailSender(Protocol):
    """Port: send a single transactional email.

    Implementations must be safe to call from async context (``await send(...)``).
    Callers treat a False return as a best-effort failure — they log a warning
    but do NOT raise and do NOT fail the request.
    """

    async def send(self, to: str, subject: str, body: str) -> bool:
        """Send an email to ``to`` with ``subject`` and plain-text ``body``.

        Returns:
            True  — message was handed off to the transport layer (delivery
                    not guaranteed; SMTP might still bounce).
            False — transport failed (connection error, auth failure, etc.).
        """
        ...
