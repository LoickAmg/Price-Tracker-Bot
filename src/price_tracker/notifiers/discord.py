"""Notification Discord via webhook — aucune librairie tierce, un simple POST."""

from __future__ import annotations

import logging
import os

import requests

from price_tracker.history import PriceChange
from price_tracker.notifiers import format_drop_message

logger = logging.getLogger(__name__)

_DISCORD_CONTENT_LIMIT = 2000


def send_discord_notification(drops: list[PriceChange]) -> bool:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL absent — notification Discord ignorée.")
        return False

    content = format_drop_message(drops)
    if len(content) > _DISCORD_CONTENT_LIMIT:
        content = content[: _DISCORD_CONTENT_LIMIT - 1] + "…"

    try:
        response = requests.post(webhook_url, json={"content": content}, timeout=10)
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("Échec de l'envoi de la notification Discord (run non bloqué).")
        return False

    return True
