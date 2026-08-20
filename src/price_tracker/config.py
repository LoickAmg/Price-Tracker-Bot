"""Chargement de la configuration des produits suivis (products.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfigError(Exception):
    """Configuration invalide dans products.yaml."""


@dataclass(frozen=True)
class Product:
    """Un produit à suivre : où aller, et comment en extraire le prix."""

    id: str
    name: str
    url: str
    selector: str
    currency: str = "EUR"

    def __post_init__(self) -> None:
        if not self.id or not self.id.replace("-", "").replace("_", "").isalnum():
            raise ConfigError(
                f"id de produit invalide : {self.id!r} "
                "(lettres/chiffres/tirets uniquement, utilisé comme clé d'historique)"
            )
        if not self.url.startswith(("http://", "https://")):
            raise ConfigError(f"url invalide pour {self.id!r} : {self.url!r}")
        if not self.selector.strip():
            raise ConfigError(f"selector vide pour {self.id!r}")


def load_products(config_path: str | Path) -> list[Product]:
    """Lit et valide products.yaml. Lève ConfigError si un produit est mal formé."""
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"fichier de config introuvable : {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("products")
    if not isinstance(entries, list) or not entries:
        raise ConfigError(
            "products.yaml doit contenir une clé 'products' avec au moins un produit"
        )

    products: list[Product] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(
                f"produit #{i} : chaque entrée doit être un objet (name/url/selector)"
            )
        try:
            product = Product(
                id=str(entry["id"]),
                name=str(entry.get("name", entry["id"])),
                url=str(entry["url"]),
                selector=str(entry["selector"]),
                currency=str(entry.get("currency", "EUR")),
            )
        except KeyError as exc:
            raise ConfigError(f"produit #{i} : champ obligatoire manquant : {exc}") from exc

        if product.id in seen_ids:
            raise ConfigError(f"id de produit dupliqué : {product.id!r}")
        seen_ids.add(product.id)
        products.append(product)

    return products
