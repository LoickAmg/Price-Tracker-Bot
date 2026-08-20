"""Point d'entrée : lit products.yaml, scrape chaque produit, met à jour
l'historique, notifie en cas de baisse. Conçu pour tourner sans surveillance
via un cron GitHub Actions (voir .github/workflows/track-prices.yml).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime

from price_tracker.config import ConfigError, load_products
from price_tracker.history import load_history, save_history, update_history
from price_tracker.notifiers import notify_all
from price_tracker.scraper import ScrapeError, scrape_price

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "products.yaml"
DEFAULT_HISTORY_PATH = "docs/data/price-history.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suivi de prix — scrape et notifie les baisses.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Chemin vers products.yaml")
    parser.add_argument(
        "--history", default=DEFAULT_HISTORY_PATH, help="Chemin vers price-history.json"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape et affiche les résultats sans écrire l'historique ni notifier",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)

    try:
        products = load_products(args.config)
    except ConfigError as exc:
        logger.error("Configuration invalide : %s", exc)
        return 1

    history = load_history(args.history)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    changes = []
    errors = []
    for product in products:
        try:
            price = scrape_price(product)
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

    # Le run réussit tant qu'au moins un produit a été scrapé — un site cassé
    # ne doit pas faire échouer tout le workflow (les autres restent utiles).
    if errors and len(errors) == len(products):
        logger.error("Aucun produit n'a pu être scrapé.")
        return 1
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
