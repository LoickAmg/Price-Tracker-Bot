"""Scraping générique : une URL + un sélecteur CSS suffisent pour n'importe quel site.

Pas de parseur spécifique à un site en particulier — plus fragile qu'un parseur
sur-mesure (un site qui change son HTML casse le sélecteur), mais ça marche
sur n'importe quelle boutique en ligne sans code supplémentaire. Voir le
README pour les limites (sites qui rendent le prix en JavaScript ne sont pas
supportés — il faudrait un navigateur headless, volontairement hors scope).
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

import requests
from bs4 import BeautifulSoup

from price_tracker.config import Product

# Un vrai User-Agent de navigateur : beaucoup de sites bloquent silencieusement
# (ou renvoient une page différente) les requêtes sans User-Agent.
_USER_AGENT = (
    "Mozilla/5.0 (compatible; price-tracker-bot/0.1; "
    "+https://github.com/) personal price tracking, one request per run"
)
_TIMEOUT_SECONDS = 15


class ScrapeError(Exception):
    """Échec du scraping ou de l'extraction du prix pour un produit donné."""


def fetch_html(url: str) -> str:
    try:
        response = requests.get(
            url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ScrapeError(f"requête échouée pour {url} : {exc}") from exc
    return response.text


def parse_price(text: str) -> Decimal:
    """Extrait un nombre décimal d'un texte de prix (symboles monétaires, espaces, etc.).

    Gère les deux conventions courantes : "1,234.56" (séparateur milliers virgule,
    décimal point) et "1 234,56" / "12,34" (séparateur décimal virgule, à l'européenne).
    C'est une heuristique, pas un parseur i18n complet — suffisant pour un usage
    personnel, mais vérifie le résultat si tu ajoutes un site avec un format inhabituel.
    """
    cleaned = re.sub(r"[^\d,.\-]", "", text)
    if not cleaned or not re.search(r"\d", cleaned):
        raise ScrapeError(f"aucun nombre trouvé dans le texte de prix : {text!r}")

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) in (1, 2):
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ScrapeError(f"impossible de convertir {text!r} en prix") from exc


def extract_price(html: str, selector: str) -> Decimal:
    soup = BeautifulSoup(html, "html.parser")
    element = soup.select_one(selector)
    if element is None:
        raise ScrapeError(f"sélecteur CSS introuvable dans la page : {selector!r}")
    return parse_price(element.get_text())


def scrape_price(product: Product) -> Decimal:
    """Récupère le prix courant d'un produit. Lève ScrapeError en cas d'échec."""
    html = fetch_html(product.url)
    try:
        return extract_price(html, product.selector)
    except ScrapeError as exc:
        raise ScrapeError(f"{product.id} : {exc}") from exc
