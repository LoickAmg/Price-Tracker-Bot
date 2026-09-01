"""Historique des prix — un simple fichier JSON versionné dans le repo Git.

Pas de base de données : le workflow GitHub Actions commit ce fichier après
chaque run (voir .github/workflows/track-prices.yml). Ça garde tout dans un
seul endroit, sans service externe à payer/maintenir, et l'historique reste
consultable directement dans les diffs Git.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from price_tracker.config import TrackingConfig

HistoryData = dict[str, Any]


@dataclass(frozen=True)
class PriceChange:
    """Un changement de prix détecté pour un produit lors du run courant."""

    product_id: str
    name: str
    url: str
    currency: str
    previous: Decimal | None
    current: Decimal

    @property
    def is_first_record(self) -> bool:
        return self.previous is None

    @property
    def is_drop(self) -> bool:
        return self.previous is not None and self.current < self.previous


def load_history(path: str | Path) -> HistoryData:
    p = Path(path)
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def save_history(path: str | Path, history: HistoryData) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # indent + clés triées : diffs Git lisibles d'un run à l'autre
    p.write_text(
        json.dumps(history, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def update_history(
    history: HistoryData,
    product: TrackingConfig,
    price: Decimal,
    timestamp: str,
) -> PriceChange | None:
    """Met à jour l'historique en place. `timestamp` est une chaîne ISO 8601 UTC.

    Renvoie un PriceChange si le prix est nouveau ou a changé depuis le dernier
    relevé enregistré (utilisé pour décider s'il faut notifier), None si le
    prix est identique au dernier relevé (on met juste `last_checked` à jour).
    """
    entry = history.setdefault(
        product.id,
        {
            "name": product.name,
            "url": product.url,
            "currency": product.currency,
            "last_checked": timestamp,
            "history": [],
        },
    )
    entry["name"] = product.name
    entry["url"] = product.url
    entry["currency"] = product.currency
    entry["last_checked"] = timestamp

    price_history: list[dict[str, str]] = entry["history"]
    previous_price = Decimal(price_history[-1]["price"]) if price_history else None

    if previous_price is not None and previous_price == price:
        return None

    price_history.append({"timestamp": timestamp, "price": str(price)})
    return PriceChange(
        product_id=product.id,
        name=product.name,
        url=product.url,
        currency=product.currency,
        previous=previous_price,
        current=price,
    )
