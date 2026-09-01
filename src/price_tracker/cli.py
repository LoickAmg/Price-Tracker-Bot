"""Point d'entrée CLI V2.

- ``run``  : lit products.yaml, scrape chaque produit, met à jour l'historique
  et notifie (mode historique, celui du cron GitHub Actions).
- ``add``  : ajoute un produit par intention — Auto résout et teste, Expert
  permet de verrouiller la stratégie. N'écrit rien en ``--dry-run``.
- ``test`` : Playground : teste l'extraction sur une URL et liste les candidats
  avec leur confiance (sans rien enregistrer).

Rétro-compatibilité : l'invocation historique ``price-tracker [--config
--history --dry-run]`` (sans sous-commande) continue d'équivaloir à ``run``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from price_tracker.config import (
    AlertMode,
    ConfigError,
    Level,
    ProductIntent,
    Strategy,
    TrackingConfig,
    load_configs,
    save_configs,
)
from price_tracker.history import load_history, save_history, update_history
from price_tracker.notifiers import notify_all
from price_tracker.resolver import ResolveError, StrategyBank, resolve_intent
from price_tracker.scraper import ScrapeError, scrape_config, test_extraction

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "products.yaml"
DEFAULT_HISTORY_PATH = "docs/data/price-history.json"
DEFAULT_BANK_PATH = "strategy-bank.json"

_KNOWN_COMMANDS = {"run", "add", "test"}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Chemin vers products.yaml")
    common.add_argument(
        "--history", default=DEFAULT_HISTORY_PATH, help="Chemin vers price-history.json"
    )
    common.add_argument(
        "--bank", default=DEFAULT_BANK_PATH, help="Chemin vers la banque de stratégies"
    )
    common.add_argument(
        "--dry-run",
        action="store_true",
        help="Résout/scrape et affiche les résultats sans écrire ni notifier",
    )

    parser = argparse.ArgumentParser(
        prog="price-tracker", description="Suivi de prix — un moteur, trois niveaux."
    )
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser(
        "run",
        parents=[common],
        help="Scrape les produits configurés et notifie les baisses",
    )
    add = sub.add_parser(
        "add",
        parents=[common],
        help="Ajoute un produit par intention (colle un lien)",
    )
    add.add_argument("url", help="URL du produit à surveiller")
    add.add_argument("--name", help="Nom du produit (sinon domaine · prix)")
    add.add_argument("--target", type=str, help="Prix cible (alerte sous ce prix, ex. 800)")
    add.add_argument(
        "--level",
        choices=[level.value for level in Level],
        default=Level.AUTO.value,
        help="Niveau de contrôle (auto/custom/expert)",
    )
    add.add_argument(
        "--strategy",
        choices=[s.value for s in Strategy],
        default=None,
        help="Stratégie d'extraction à verrouiller (custom/expert)",
    )

    test = sub.add_parser("test", help="Playground : teste l'extraction d'une URL")
    test.add_argument("url", help="URL à tester")
    test.add_argument(
        "--strategy",
        choices=[s.value for s in Strategy],
        default=Strategy.AUTO.value,
        help="Stratégie à tester (défaut : auto)",
    )
    test.add_argument("--selector", help="Sélecteur CSS (strategy css)")
    test.add_argument("--xpath", help="Expression XPath (strategy xpath)")
    test.add_argument("--regex", help="Expression régulière de prix (strategy regex)")
    test.add_argument("--browser", action="store_true", help="Rendu JavaScript via Playwright")
    return parser


# ------------------------------------------------------------------- run


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        products = load_configs(args.config)
    except ConfigError as exc:
        logger.error("Configuration invalide : %s", exc)
        return 1

    history = load_history(args.history)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    changes = []
    errors = []
    for product in products:
        try:
            price = scrape_config(product)
        except ScrapeError as exc:
            logger.warning("Échec du scraping pour %s : %s", product.id, exc)
            errors.append(product.id)
            continue

        change = update_history(history, product, price, timestamp)
        logger.info("%s : %s %s", product.name, price, product.currency)
        if change is not None:
            changes.append(change)

    if args.dry_run:
        logger.info("--dry-run : historique et notifications non écrits.")
    else:
        save_history(args.history, history)

    drops = [c for c in changes if c.is_drop]
    if drops and not args.dry_run:
        sent = notify_all(drops)
        logger.info("Notifications envoyées : %s", sent)
    elif drops:
        for drop in drops:
            logger.info("Baisse détectée (non notifiée, --dry-run) : %s", drop.name)

    if errors:
        logger.warning(
            "%d/%d produits n'ont pas pu être scrapés : %s", len(errors), len(products), errors
        )

    if errors and len(errors) == len(products):
        logger.error("Aucun produit n'a pu être scrapé.")
        return 1
    return 0


# ------------------------------------------------------------------- add


def _read_products(config_path: str) -> list[TrackingConfig]:
    if not Path(config_path).exists():
        return []
    return load_configs(config_path)


def _cmd_add(args: argparse.Namespace) -> int:
    target = None
    if args.target:
        try:
            target = Decimal(args.target)
        except InvalidOperation:
            logger.error("Prix cible invalide : %r", args.target)
            return 1

    intent = ProductIntent(
        query=args.name or "",
        url=args.url,
        target_price=target,
        alert_mode=AlertMode.PRICE_BELOW,
        level=Level(args.level),
    )

    bank = StrategyBank(Path(args.bank))
    try:
        existing = _read_products(args.config)
    except ConfigError:
        existing = []
    existing_ids = {c.id for c in existing}

    try:
        resolved = resolve_intent(intent, existing_ids=existing_ids, bank=bank)
    except ResolveError as exc:
        logger.error("Impossible de résoudre l'intention : %s", exc)
        return 1

    config = resolved.config
    if args.strategy:
        config = TrackingConfig(**dict(config.__dict__, strategy=Strategy(args.strategy)))

    print(f"Résolution pour {config.url}")
    print(f"  nom                    : {config.name}")
    print(f"  confiance de détection : {resolved.confidence:.0%}")
    print(f"  stratégie              : {config.strategy.value}")
    print(f"  prix cible             : {config.alert.threshold or '—'}")
    if config.alert.threshold is not None:
        print(f"  alerte                 : sous {config.alert.threshold} {config.currency}")

    if args.dry_run:
        print("  (--dry-run : rien n'est écrit)")
        return 0

    if any(c.id == config.id for c in existing):
        existing_ids.add(config.id)
        config = TrackingConfig(**dict(config.__dict__, id=_unique_id(config.id, existing_ids)))
    existing.append(config)
    save_configs(args.config, existing)
    print(f"  enregistré             : {config.id}")
    return 0


def _unique_id(base: str, existing: set[str]) -> str:
    candidate, counter = base, 1
    while candidate in existing:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


# ------------------------------------------------------------------ test


def _cmd_test(args: argparse.Namespace) -> int:
    result = test_extraction(
        args.url,
        args.strategy,
        selector=args.selector,
        xpath=args.xpath,
        regex=args.regex,
        browser=args.browser,
    )
    print(f"test {args.url}")
    print(
        f"  statut     : {result.status_code or '—'}  "
        f"temps {result.response_time_ms or 0} ms  taille {result.size_bytes or 0} o"
    )
    print(f"  diagnostic : {result.diagnostic}")
    if result.candidates:
        best = result.best
        print("  candidats  :")
        for c in sorted(result.candidates, key=lambda x: -x.confidence):
            mark = "◀ choisi" if c is best else ""
            print(
                f"    {c.price:>12}  {c.strategy.value:<7} conf {c.confidence:.0%}  "
                f"{c.source}  {mark}"
            )
    else:
        print("  → aucun prix détecté.")
    return 0 if result.best is not None else 1


# ----------------------------------------------------------------- entry


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()

    args_list = argv if argv is not None else sys.argv[1:]
    if args_list and args_list[0] in _KNOWN_COMMANDS:
        args = parser.parse_args(args_list)
    else:
        # Historique : pas de sous-commande → run avec les options racine.
        args = parser.parse_args(["run", *args_list])
        args.command = "run"

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "add":
        return _cmd_add(args)
    if args.command == "test":
        return _cmd_test(args)
    parser.error(f"commande inconnue : {args.command}")
    return 2


def run(argv: list[str] | None = None) -> int:
    """API : même entrée, utilisée par __main__.py et les tests."""
    return main(argv)


if __name__ == "__main__":
    sys.exit(main())
