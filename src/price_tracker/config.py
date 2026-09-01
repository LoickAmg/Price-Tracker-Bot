"""Modèle V2 du Price Tracker : intentions, configuration de suivi et persistence.

Deux objets, une frontière nette (voir docs/ux-ajouter-produit.md) :

- ``ProductIntent`` : ce que veut l'utilisateur (« surveille ce lien sous 800 € »).
- ``TrackingConfig`` : ce que le moteur doit faire (URL, stratégie d'extraction,
  validation, alertes, fréquence).

Tous les niveaux (Auto / Custom / Expert) finissent par produire une
``TrackingConfig`` unique — un seul moteur, jamais deux pipelines.
La v1 (products.yaml avec ``selector`` seul) reste lisible : elle est montée
automatiquement en ``strategy: css``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Configuration invalide (products.yaml ou données fournies par l'API)."""


class Strategy(StrEnum):
    """Stratégies d'extraction du moteur (une seule pipeline, N extracteurs)."""

    AUTO = "auto"
    JSONLD = "jsonld"
    CSS = "css"
    XPATH = "xpath"
    REGEX = "regex"
    BROWSER = "browser"  # Playwright, pour les prix rendus en JavaScript


class Level(StrEnum):
    """Niveau de contrôle exprimé par l'utilisateur au moment de l'ajout."""

    AUTO = "auto"
    CUSTOM = "custom"
    EXPERT = "expert"


class AlertMode(StrEnum):
    """Déclencheur d'alerte (mode "surveillance", pas "scraping")."""

    PRICE_BELOW = "price_below"  # sous le prix cible
    DROP_PCT = "drop_pct"  # baisse > x % sur un relevé
    ANY_CHANGE = "any_change"  # toute variation de prix


@dataclass(frozen=True)
class ProductIntent:
    """Intention brute de l'utilisateur, avant résolution."""

    query: str = ""
    url: str | None = None
    target_price: Decimal | None = None
    alert_mode: AlertMode = AlertMode.PRICE_BELOW
    level: Level = Level.AUTO


@dataclass(frozen=True)
class Validation:
    """Bornes de vraisemblance appliquées au prix extrait."""

    min_price: Decimal | None = None
    max_price: Decimal | None = None

    def validate(self, price: Decimal) -> bool:
        if self.min_price is not None and price < self.min_price:
            return False
        if self.max_price is not None and price > self.max_price:
            return False
        return True


@dataclass(frozen=True)
class AlertRule:
    """Règle d'alerte d'un produit."""

    mode: AlertMode = AlertMode.PRICE_BELOW
    threshold: Decimal | None = None  # prix cible (price_below) ou % (drop_pct)


@dataclass(frozen=True)
class TrackingConfig:
    """Configuration complète d'un produit — le modèle unique du moteur."""

    id: str
    name: str
    url: str
    level: Level = Level.AUTO
    strategy: Strategy = Strategy.AUTO
    currency: str = "EUR"
    selector: str | None = None
    xpath: str | None = None
    regex: str | None = None
    validation: Validation = field(default_factory=Validation)
    alert: AlertRule = field(default_factory=AlertRule)
    interval_hours: int = 6
    confidence: float | None = None
    domain: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.id):
            raise ConfigError(
                f"id de produit invalide : {self.id!r} "
                "(lettres/chiffres/tirets/underscores uniquement)"
            )
        if not self.url.startswith(("http://", "https://")):
            raise ConfigError(f"url invalide pour {self.id!r} : {self.url!r}")
        if self.interval_hours < 1:
            raise ConfigError(f"intervalle invalide pour {self.id!r}")

    # ------------------------------------------------------------------ YAML

    def to_dict(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "level": self.level.value,
            "strategy": self.strategy.value,
            "currency": self.currency,
            "interval_hours": self.interval_hours,
            "alert": {"mode": self.alert.mode.value},
        }
        if self.alert.threshold is not None:
            base["alert"]["threshold"] = str(self.alert.threshold)
        if self.selector:
            base["selector"] = self.selector
        if self.xpath:
            base["xpath"] = self.xpath
        if self.regex:
            base["regex"] = self.regex
        if self.validation.min_price is not None or self.validation.max_price is not None:
            base["validation"] = {}
            if self.validation.min_price is not None:
                base["validation"]["min"] = str(self.validation.min_price)
            if self.validation.max_price is not None:
                base["validation"]["max"] = str(self.validation.max_price)
        if self.confidence is not None:
            base["confidence"] = round(self.confidence, 2)
        if self.domain:
            base["domain"] = self.domain
        return base

    @classmethod
    def from_dict(cls, entry: dict[str, Any], index: int) -> TrackingConfig:
        if not isinstance(entry, dict):
            raise ConfigError(f"produit #{index} : chaque entrée doit être un objet")
        try:
            raw_id = str(entry["id"])
            url = str(entry["url"])
        except KeyError as exc:
            raise ConfigError(f"produit #{index} : champ obligatoire manquant : {exc}") from exc

        level = _parse_enum(Level, entry.get("level"), Level.AUTO, f"produit #{index} 'niveau'")
        strategy = _parse_enum(
            Strategy, entry.get("strategy"), Strategy.AUTO, f"produit #{index} 'stratégie'"
        )

        # v1 → v2 : un selector seul (réponse CSS) devient strategy: css.
        if "selector" in entry and "strategy" not in entry:
            strategy = Strategy.CSS

        validation_raw = entry.get("validation") or {}
        validation = Validation(
            min_price=_parse_decimal(validation_raw.get("min"), None),
            max_price=_parse_decimal(validation_raw.get("max"), None),
        )

        alert_raw = entry.get("alert") or {}
        alert_mode = alert_raw.get("mode", AlertMode.PRICE_BELOW.value)
        alert = AlertRule(
            mode=_parse_enum(AlertMode, alert_mode, AlertMode.PRICE_BELOW, "alerte"),
            threshold=_parse_decimal(alert_raw.get("threshold"), None),
        )

        return cls(
            id=raw_id,
            name=str(entry.get("name", raw_id)),
            url=url,
            level=level,
            strategy=strategy,
            currency=str(entry.get("currency", "EUR")),
            selector=str(entry["selector"]) if entry.get("selector") else None,
            xpath=str(entry["xpath"]) if entry.get("xpath") else None,
            regex=str(entry["regex"]) if entry.get("regex") else None,
            validation=validation,
            alert=alert,
            interval_hours=int(entry.get("interval_hours", 6)),
            confidence=_parse_float(entry.get("confidence"), None),
            domain=str(entry.get("domain", "")),
        )


def _parse_enum(cls: type[Enum], value: Any, default: Any = None, where: str = "") -> Enum:
    if value is None:
        return default
    try:
        return cls(value)
    except ValueError as exc:
        choices = ", ".join(m.value for m in cls)
        raise ConfigError(f"{where} : valeur inconnue {value!r} (choix : {choices})") from exc


def _parse_decimal(value: Any, default: Decimal | None) -> Decimal | None:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ConfigError(f"décimale invalide : {value!r}") from exc


def _parse_float(value: Any, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"nombre invalide : {value!r}") from exc


# ----------------------------------------------------------------- functions


def load_configs(config_path: str | Path) -> list[TrackingConfig]:
    """Lit products.yaml (v1 ou v2). Lève ConfigError si un produit est mal formé."""
    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"fichier de config introuvable : {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("products")
    if not isinstance(entries, list) or not entries:
        raise ConfigError("products.yaml doit contenir une clé 'products' avec au moins un produit")

    configs: list[TrackingConfig] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(entries):
        config = TrackingConfig.from_dict(entry, i)
        if config.id in seen_ids:
            raise ConfigError(f"id de produit dupliqué : {config.id!r}")
        seen_ids.add(config.id)
        configs.append(config)
    return configs


def save_configs(config_path: str | Path, configs: list[TrackingConfig]) -> None:
    """Écrit products.yaml v2. Préserve l'en-tête commenté s'il existe."""
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    header = _extract_header(path) if path.exists() else _DEFAULT_HEADER
    payload: dict[str, Any] = {"products": [c.to_dict() for c in configs]}
    yaml_text = yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    path.write_text(header + yaml_text, encoding="utf-8")


_DEFAULT_HEADER = (
    "# Produits suivis — format V2. Un seul moteur pour trois niveaux :\n"
    "#   level: auto/custom/expert · strategy: auto/jsonld/css/xpath/regex/browser\n"
    "# L'UI et le CLI génèrent ces entrées ; on peut aussi les écrire à la main.\n"
    "\n"
)

_HEADER_PREFIXES = ("#",)


def _extract_header(path: Path) -> str:
    """Extrait le bloc de commentaires et un trailing blank line avant l'objet."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header: list[str] = []
    for line in lines:
        if line.startswith(_HEADER_PREFIXES):
            header.append(line)
        else:
            break
    if header:
        header.append("")
    return "\n".join(header)


# Rétro-compatibilité : la v1 exposait Product/load_products.
def load_products(config_path: str | Path) -> list[TrackingConfig]:
    """Alias de load_configs, conservé pour les modules historiques."""
    return load_configs(config_path)
