"""Notifications de baisse de prix — toutes optionnelles.

Chaque canal (Discord, email) ne s'active que si sa config est présente dans
l'environnement (secrets GitHub Actions). Aucun des deux n'étant configuré,
le run se termine quand même normalement — jamais bloquant, comme le repli
automatique du générateur LLM dans le Poem Generator.
"""

from __future__ import annotations

from price_tracker.history import PriceChange


def format_drop_message(drops: list[PriceChange]) -> str:
    lines = [f"📉 {len(drops)} baisse(s) de prix détectée(s) :", ""]
    for drop in drops:
        lines.append(
            f"• {drop.name} : {drop.previous} → {drop.current} {drop.currency}\n  {drop.url}"
        )
    return "\n".join(lines)


def notify_all(drops: list[PriceChange]) -> dict[str, bool]:
    """Envoie les notifications configurées. Renvoie quels canaux ont effectivement envoyé."""
    from price_tracker.notifiers.discord import send_discord_notification
    from price_tracker.notifiers.email import send_email_notification

    if not drops:
        return {"discord": False, "email": False}

    return {
        "discord": send_discord_notification(drops),
        "email": send_email_notification(drops),
    }
