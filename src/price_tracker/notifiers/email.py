"""Notification email via SMTP — compatible avec la plupart des fournisseurs
(Gmail avec mot de passe d'application, Resend, SendGrid en mode SMTP, etc.).
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

from price_tracker.history import PriceChange
from price_tracker.notifiers import format_drop_message

logger = logging.getLogger(__name__)

_REQUIRED_VARS = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO")


def send_email_notification(drops: list[PriceChange]) -> bool:
    config = {name: os.environ.get(name) for name in _REQUIRED_VARS}
    missing = [name for name, value in config.items() if not value]
    if missing:
        logger.info(
            "Variables SMTP manquantes (%s) — notification email ignorée.",
            ", ".join(missing),
        )
        return False

    port = int(os.environ.get("SMTP_PORT", "587"))
    from_addr = os.environ.get("EMAIL_FROM") or config["SMTP_USER"]

    message = EmailMessage()
    message["Subject"] = f"📉 Baisse de prix — {len(drops)} produit(s)"
    message["From"] = from_addr
    message["To"] = config["EMAIL_TO"]
    message.set_content(format_drop_message(drops))

    try:
        with smtplib.SMTP(config["SMTP_HOST"], port, timeout=15) as server:
            server.starttls()
            server.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
            server.send_message(message)
    except (smtplib.SMTPException, OSError):
        logger.exception("Échec de l'envoi de la notification email (run non bloqué).")
        return False

    return True
