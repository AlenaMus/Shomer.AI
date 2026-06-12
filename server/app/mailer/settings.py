"""Configuration for the Mailer module.

All env vars are prefixed with ``MAILER_`` so they are namespaced and
obvious in ``server/.env``.

Gmail app-password example::

    MAILER_BACKEND=smtp
    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USERNAME=your.address@gmail.com
    SMTP_PASSWORD=<16-char app password from Google Account → Security>
    SMTP_FROM=your.address@gmail.com

Any other STARTTLS-capable SMTP server works the same way.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MailerSettings(BaseSettings):
    """Settings for the mailer module.

    ``MAILER_`` prefix for mailer-specific settings; SMTP vars are unprefixed
    for broad compatibility with hosting providers that set SMTP_* directly.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
    )

    mailer_backend: str = Field(
        default="log",
        alias="MAILER_BACKEND",
        description="'log' (default) or 'smtp'.  Log adapter requires no config.",
    )

    smtp_host: str = Field(
        default="",
        alias="SMTP_HOST",
        description="SMTP server hostname (e.g. smtp.gmail.com).",
    )
    smtp_port: int = Field(
        default=587,
        alias="SMTP_PORT",
        description="SMTP port (default 587 = STARTTLS).",
    )
    smtp_username: str = Field(
        default="",
        alias="SMTP_USERNAME",
        description="SMTP login username (usually your email address).",
    )
    smtp_password: str = Field(
        default="",
        alias="SMTP_PASSWORD",
        description="SMTP login password or app-specific password.",
    )
    smtp_from: str = Field(
        default="",
        alias="SMTP_FROM",
        description=(
            "From address for outgoing mail.  Defaults to SMTP_USERNAME when empty."
        ),
    )

    @property
    def from_address(self) -> str:
        """Return the effective From address (SMTP_FROM or fall back to SMTP_USERNAME)."""
        return self.smtp_from.strip() or self.smtp_username.strip()
