"""Resolver V2 : transforme une intention en TrackingConfig testée.

Flux (voir docs/ux-ajouter-produit.md, § 2) :

1. L'intention (lien / description / prix cible) est résolue :
   - si une URL est fournie, on teste réellement l'extraction dessus ;
   - sinon, l'intention est un clic "description" — le resolver n'a qu'une
     requête, et l'UI doit proposer une liste (pas encore implémenté ici).
2. La banque de stratégies par domaine est consultée pour préférer une
   stratégie déjà validée (auto-apprentissage léger).
3. Une TrackingConfig pré-remplie + une confiance sont produites.

Fin de flux : `ProductIntent -> Resolver -> TrackingConfig` (proposition § 3).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from price_tracker.config import (
    AlertRule,
    Level,
    ProductIntent,
    Strategy,
    TrackingConfig,
    Validation,
)
from price_tracker.scraper import domain_of, test_extraction


class ResolveError(Exception):
    """L'intention n'a pas pu être résolue en configuration valide."""


@dataclass(frozen=True)
class ResolveResult:
    """Résultat de la résolution : configuration proposée + candidats."""

    config: TrackingConfig
    confidence: float
    candidates: list  # list[scraper.Candidate]
    diagnostic: str = ""


@dataclass
class StrategyBank:
    """Banque de stratégies apprenante : domaine → stratégie validée.

    Endroit où le moteur "apprend" ce qui marche par domaine ; les entrées
    sont écrites à la volée quand un test réussit, pour être réutilisées.
    """

    path: Path

    def load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def remember(self, domain: str, strategy: Strategy, confidence: float) -> None:
        data = self.load()
        entry = dict(data.get(domain, {}))
        if confidence > float(entry.get("confidence", 0)):
            entry.update({"strategy": strategy.value, "confidence": round(confidence, 2)})
            data[domain] = entry
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def preferred(self, domain: str) -> Strategy | None:
        entry = self.load().get(domain)
        if not entry:
            return None
        try:
            return Strategy(entry["strategy"])
        except (KeyError, ValueError):
            return None

    def best_candidate(self, candidates) -> object | None:
        """Candidat le plus confiant parmi une liste de Candidate."""
        if not candidates:
            return None
        return max(candidates, key=lambda c: (c.confidence, c.strategy.value))


def slugify(text: str) -> str:
    """Produit un id lisible à partir d'un nom de produit."""
    clean = "".join(c if c.isalnum() else "-" for c in text.lower())
    clean = re.sub(r"-{2,}", "-", clean).strip("-")
    return clean or "produit"


def _dedupe_id(base: str, existing: set[str]) -> str:
    candidate = base
    counter = 1
    while candidate in existing:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def resolve_intent(
    intent: ProductIntent,
    *,
    existing_ids: set[str],
    bank: StrategyBank | None = None,
) -> ResolveResult:
    """Résout une intention contenant une URL. N'écrit rien dans products.yaml."""
    if not intent.url:
        raise ResolveError(
            "intention sans URL : la sélection de produit par description n'est "
            "pas encore implémentée — fournir un lien col / url"
        )

    domain = domain_of(intent.url)
    if domain.startswith("www."):
        domain = domain.removeprefix("www.")

    preferred = bank.preferred(domain) if bank else None
    candidates: list = []

    # Test prioritaire : stratégie connue pour le domaine, sinon auto.
    test_url = intent.url
    if preferred is not None:
        result = test_extraction(test_url, preferred)
        if result.best is not None:
            candidates = result.candidates
        else:
            result = test_extraction(test_url, Strategy.AUTO)
            candidates = result.candidates
    else:
        result = test_extraction(test_url, Strategy.AUTO)
        candidates = result.candidates

    best = max(candidates, key=lambda c: (c.confidence, c.strategy.value)) if candidates else None
    if best is None:
        raise ResolveError(result.diagnostic or "aucune extraction possible")

    # Apprentissage : mémoriser la stratégie qui a gagné, si elle est fiable.
    if bank is not None and best.confidence >= 0.7:
        bank.remember(domain, best.strategy, best.confidence)

    # En Automatique le moteur re-détecte à chaque relevé ; en Custom/Expert la
    # stratégie gagnante est verrouillée dans la configuration.
    if intent.level in (Level.CUSTOM, Level.EXPERT):
        locked = best.strategy
    else:
        locked = Strategy.AUTO

    # Nom par défaut : domaine + prix, sinon la description fournie.
    name = intent.query.strip() or f"{domain} · {best.price}"
    config = TrackingConfig(
        id=_dedupe_id(slugify(name), existing_ids),
        name=name,
        url=test_url,
        level=intent.level,
        strategy=locked,
        confidence=round(best.confidence, 2),
        domain=domain,
        validation=Validation(),
        alert=AlertRule(
            mode=intent.alert_mode,
            threshold=intent.target_price,
        ),
    )

    return ResolveResult(
        config=config,
        confidence=best.confidence,
        candidates=candidates,
        diagnostic=result.diagnostic,
    )
