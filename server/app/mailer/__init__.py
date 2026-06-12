"""Mailer module — transactional email sending.

Public surface:

  * Port (import everywhere except the composition root)::

        from server.app.mailer import EmailSender

  * Concrete adapters + settings (import ONLY in server/app/main.py lifespan())::

        from server.app.mailer import LogEmailSender, SmtpEmailSender, MailerSettings

Named ``mailer`` (not ``email``) to avoid shadowing the stdlib ``email`` package.
"""

from __future__ import annotations

from .log_adapter import LogEmailSender
from .protocol import EmailSender
from .settings import MailerSettings
from .smtp_adapter import SmtpEmailSender

__all__ = [
    # Port
    "EmailSender",
    # Concrete adapters + settings (composition root only)
    "LogEmailSender",
    "SmtpEmailSender",
    "MailerSettings",
]
