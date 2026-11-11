"""SMTP-Versand NUR an mich selbst (MAIL_TO). Kundenversand läuft später über onOffice sendmail."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import Settings
from .logger import get_logger

log = get_logger("mailer")


class MailError(Exception):
    pass


def build_message(settings: Settings, subject: str, html: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.mail_from
    msg["To"] = settings.mail_to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_to_self(settings: Settings, subject: str, html: str, text: str, smtp_factory=None) -> None:
    """Sendet an MAIL_TO. Andere Empfänger sind technisch ausgeschlossen."""
    settings.require_mail()
    msg = build_message(settings, subject, html, text)
    if msg["To"] != settings.mail_to or msg.get("Cc") or msg.get("Bcc"):
        raise MailError("Mailer darf nur an MAIL_TO senden")
    sec = settings.smtp_security
    ctx = ssl.create_default_context()
    try:
        if smtp_factory is not None:
            server = smtp_factory(settings.smtp_host, settings.smtp_port)
        elif sec == "ssl":
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=30)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
        with server:
            if sec == "starttls" and smtp_factory is None:
                server.starttls(context=ctx)
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg, to_addrs=[settings.mail_to])
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"SMTP-Fehler: {type(exc).__name__}") from exc
    log.info("Mail an mich versendet (Betreff-Länge %d)", len(subject))
