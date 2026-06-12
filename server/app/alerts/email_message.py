"""Shared email-message builder for alert-email channels.

Used by both ``GmailApiNotifier`` (RFC 822 + base64url for the Gmail API) and
``SmtpEmailNotifier`` (stdlib ``smtplib`` MIME).

Reference: docs/design/alerts/design.md §2.5 (NotificationChannel Protocol).

Keeping the message-building logic here (DRY) means that both email notifiers
produce identical Hebrew alert content — the only difference is the transport
layer (Gmail API vs. SMTP).
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.message import EmailMessage
from email.mime.text import MIMEText

from ..schemas import AlertRequest

_SEVERITY_LABEL = {"low": "נמוכה", "medium": "בינונית", "high": "גבוהה", "critical": "קריטית"}
_SEVERITY_ICON = {"low": "🟡", "medium": "🟠", "high": "🔴", "critical": "🚨"}


def build_alert_subject(label: str) -> str:
    """Return the Hebrew alert email subject line.

    Example: ``"Shomer.AI · התראה: violence"``
    """
    return f"Shomer.AI · התראה: {label}"


def build_alert_body(request: AlertRequest) -> str:
    """Return the Hebrew plain-text alert email body.

    Identical content regardless of transport (Gmail API or SMTP).
    """
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    icon = _SEVERITY_ICON.get(request.severity, "🔔")
    sev_he = _SEVERITY_LABEL.get(request.severity, request.severity)
    return (
        f"Shomer.AI — התראת תוכן פוגעני\n"
        f"{'─' * 40}\n\n"
        f"{icon} רמת חומרה: {sev_he}\n"
        f"קטגוריה: {request.label}\n"
        f"ילד: {request.child_id}\n\n"
        f"ציטוט:\n  \"{request.quote}\"\n\n"
        f"הסבר:\n  {request.explanation}\n\n"
        f"מקור: {request.source}\n"
        f"זמן: {ts}\n"
        f"מזהה מעקב: {request.trace_id}\n\n"
        f"{'─' * 40}\n"
        f"לפרטים נוספים, היכנסו ללוח המחוונים של Shomer.AI.\n"
    )


def build_email_message(
    to_address: str,
    from_address: str,
    request: AlertRequest,
) -> EmailMessage:
    """Build a stdlib ``EmailMessage`` for SMTP transport.

    UTF-8 plain text, Hebrew subject and body.  Used by ``SmtpEmailNotifier``.
    """
    msg = EmailMessage()
    msg["To"] = to_address
    msg["From"] = from_address
    msg["Subject"] = build_alert_subject(request.label)
    msg.set_content(build_alert_body(request), charset="utf-8")
    return msg


def build_raw_message_base64url(
    to_address: str,
    from_address: str,
    request: AlertRequest,
) -> str:
    """Build an RFC 822 MIME message and return it as a base64url string.

    Gmail API requires the message to be base64url-encoded (standard base64
    with ``+`` → ``-`` and ``/`` → ``_``; Python's ``urlsafe_b64encode``
    produces the correct variant).

    Used by ``GmailApiNotifier``.
    """
    body = build_alert_body(request)
    subject = build_alert_subject(request.label)

    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to_address
    msg["From"] = from_address
    msg["Subject"] = subject

    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
