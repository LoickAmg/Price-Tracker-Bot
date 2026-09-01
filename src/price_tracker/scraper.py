"""Moteur d'extraction V2 : une seule pipeline, plusieurs stratégies.

- fetch : HTTP (requests, retries bornés) ou navigateur (Playwright, optionnel).
- extraction : JSON-LD, OpenGraph, CSS, XPath, Regex, heuristique (Auto).
- validation : bornes min/max appliquées avant d'accepter un prix.

En mode Auto, le moteur retourne des candidats avec une confiance, et le
resolver (resolver.py) choisit le meilleur pour produire une TrackingConfig.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from price_tracker.config import Strategy, TrackingConfig, Validation

_USER_AGENT = (
    "Mozilla/5.0 (compatible; price-tracker-bot/0.2; "
    "+https://github.com/) personal price tracking, one request per run"
)
_TIMEOUT_SECONDS = 15
_MAX_FETCH_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5

# Sélecteurs CSS couramment utilisés par les boutiques en ligne, dans l'ordre
# de confiance décroissante (itemprop > classes "price" explicites > listes).
_HEURISTIC_SELECTORS = (
    '[itemprop="price"]',
    "[data-price]",
    "meta[property='product:price:amount']",
    "span.price_color",
    "span.price",
    "div.price",
    ".a-price .a-offscreen",
    "p.price",
    "[class*='price']",
)

# Expression par défaut : nombre décimal à 1-2 décimales (optionnel).
_DEFAULT_REGEX = r"\d[\d\s\u00a0]*(?:[.,]\d{1,2})?"

_PRICE_STOPWORDS = ("abonnement", "subscription", "par mois", "/mois", "/month")


class ScrapeError(Exception):
    """Échec du scraping ou de l'extraction du prix."""


@dataclass(frozen=True)
class Candidate:
    """Un prix détecté, avec la stratégie qui l'a produit et une confiance."""

    price: Decimal
    strategy: Strategy
    confidence: float
    source: str


@dataclass(frozen=True)
class ExtractionResult:
    """Résultat d'un test d'extraction (Playground / resolver)."""

    url: str
    candidates: list[Candidate] = field(default_factory=list)
    diagnostic: str = ""
    status_code: int | None = None
    response_time_ms: int | None = None
    size_bytes: int | None = None

    @property
    def best(self) -> Candidate | None:
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda c: (c.confidence, c.strategy.value))


# ------------------------------------------------------------------- fetch


def fetch_html(
    url: str,
    *,
    max_attempts: int = _MAX_FETCH_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, int | None]:
    """Récupère le HTML avec retries bornés (timeouts, 429, 5xx)."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    last_error: requests.RequestException | None = None
    last_status: int | None = None
    attempts_made = 0
    for attempt in range(max_attempts):
        attempts_made += 1
        try:
            response = requests.get(
                url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDS
            )
            last_status = response.status_code
            if response.status_code == 429 or response.status_code >= 500:
                last_error = requests.HTTPError(
                    f"statut HTTP transitoire {response.status_code}", response=response
                )
                if attempt == max_attempts - 1:
                    break
                sleep(_RETRY_BACKOFF_SECONDS * (2**attempt))
                continue
            response.raise_for_status()
            return response.text, response.status_code
        except requests.RequestException as exc:
            last_error = exc
            retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError))
            if not retryable or attempt == max_attempts - 1:
                break
            sleep(_RETRY_BACKOFF_SECONDS * (2**attempt))
    assert last_error is not None
    message = (
        f"requête échouée pour {url} après {attempts_made} tentative(s) "
        f"(statut {last_status}) : {last_error}"
    )
    raise ScrapeError(message) from last_error


def fetch_html_browser(url: str, *, timeout_ms: int = 20000) -> tuple[str, int | None]:
    """Récupère le HTML rendu en JavaScript via Playwright (optionnel)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ScrapeError(
            "stratégie navigateur : installer l'extra, puis le navigateur\n"
            "  pip install -e '.[browser]'\n"
            "  playwright install chromium"
        ) from exc

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            html = page.content()
            browser.close()
    except Exception as exc:  # playwright lève beaucoup d'exceptions spécifiques
        raise ScrapeError(f"navigateur : {exc}") from exc
    return html, None


# ------------------------------------------------------------------ parse


def parse_price(text: str, *, decimal_comma: bool | None = None) -> Decimal:
    """Convertit un texte en Decimal.

    ``decimal_comma=None`` : détection heuristique des deux conventions
    ("1,234.56" et "1 234,56" / "12,34"). ``False`` = point décimal,
    ``True`` = virgule décimale.
    """
    cleaned = re.sub(r"[^\d,.\-]", "", text)
    if not cleaned or not re.search(r"\d", cleaned):
        raise ScrapeError(f"aucun nombre trouvé dans le texte de prix : {text!r}")

    if decimal_comma is None:
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
    elif decimal_comma:
        cleaned = cleaned.replace(",", ".").replace("\u00a0", "")
    else:
        cleaned = cleaned.replace(",", "")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ScrapeError(f"impossible de convertir {text!r} en prix") from exc


# ------------------------------------------------------------- extraction


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def extract_jsonld(html: str) -> list[tuple[str, Decimal, str]]:
    """Extrait les prix des blocs JSON-LD (Product/Offer). Renvoie (currency, prix, source)."""
    soup = _soup(html)
    found: list[tuple[str, Decimal, str]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk_jsonld(data):
            offers = _offers_from(node)
            for price, currency in offers:
                try:
                    found.append((currency, parse_price(str(price)), "JSON-LD"))
                except ScrapeError:
                    continue
    return found


def _walk_jsonld(node: object):
    if isinstance(node, dict):
        for item in node.get("@graph", []) if "@graph" in node else [node]:
            yield item
            for _key, value in item.items():
                if isinstance(value, (dict, list)):
                    yield from _walk_jsonld(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)


def _offers_from(node: dict) -> list[tuple[object, str]]:
    offers = node.get("offers") or node.get("aggregateOffer")
    rows: list[tuple[object, str]] = []
    if isinstance(offers, dict):
        rows.append(
            (
                offers.get("price")
                or offers.get("lowPrice")
                or (offers.get("highPrice") if offers.get("lowPrice") is None else None),
                offers.get("priceCurrency") or node.get("priceCurrency") or "EUR",
            )
        )
    elif isinstance(offers, list):
        for offer in offers:
            if isinstance(offer, dict):
                rows.append((offer.get("price"), offer.get("priceCurrency") or "EUR"))
    return [r for r in rows if isinstance(r[0], (str, int, float))]


def extract_opengraph(html: str, url: str) -> list[Candidate]:
    soup = _soup(html)
    meta = soup.find("meta", property="product:price:amount")
    if meta is None:
        return []
    try:
        price = parse_price(meta.get("content", ""))
    except ScrapeError:
        return []
    return [
        Candidate(
            price=price,
            strategy=Strategy.AUTO,
            confidence=0.8,
            source="OpenGraph product:price:amount",
        )
    ]


def extract_css(html: str, selector: str) -> list[Candidate]:
    soup = _soup(html)
    element = soup.select_one(selector)
    if element is None:
        raise ScrapeError(f"sélecteur CSS introuvable dans la page : {selector!r}")
    return [
        Candidate(
            price=parse_price(element.get_text()),
            strategy=Strategy.CSS,
            confidence=0.95,
            source=f"CSS {selector}",
        )
    ]


def extract_xpath(html: str, xpath: str) -> list[Candidate]:
    try:
        from lxml import html as lx
    except ImportError as exc:
        raise ScrapeError("stratégie XPath : installer lxml (dépendance du projet)") from exc
    tree = lx.fromstring(html)
    nodes = tree.xpath(xpath)
    if not nodes or not isinstance(nodes, list):
        raise ScrapeError(f"XPath introuvable dans la page : {xpath!r}")
    texts = []
    for node in nodes:
        texts.append(node.text_content() if hasattr(node, "text_content") else str(node))
    candidates: list[Candidate] = []
    for text in texts:
        try:
            candidates.append(
                Candidate(
                    price=parse_price(text),
                    strategy=Strategy.XPATH,
                    confidence=0.9,
                    source=f"XPath {xpath}",
                )
            )
        except ScrapeError:
            continue
    if not candidates:
        raise ScrapeError(f"XPath trouvé mais aucun prix saisissable : {xpath!r}")
    return candidates


def extract_regex(html: str, pattern: str | None, *, base_conf: float = 0.4) -> list[Candidate]:
    compiled = re.compile(pattern or _DEFAULT_REGEX)
    texts = re.findall(r">([^<>]{0,60})<", html)
    seen: set[str] = set()
    candidates: list[Candidate] = []
    for text in texts:
        for match in compiled.findall(text):
            raw = match if isinstance(match, str) else match[0]
            candidate_str = _clean_price_text(raw)
            if not candidate_str or candidate_str in seen:
                continue
            seen.add(candidate_str)
            try:
                candidates.append(
                    Candidate(
                        price=parse_price(candidate_str),
                        strategy=Strategy.REGEX,
                        confidence=base_conf,
                        source=f'regex "{pattern or _DEFAULT_REGEX}"',
                    )
                )
            except ScrapeError:
                continue
    if not candidates:
        raise ScrapeError(
            f"aucun prix trouvé par l'expression régulière : {pattern or _DEFAULT_REGEX!r}"
        )
    return candidates


def _clean_price_text(text: str) -> str:
    """Normalise un morceau de page (symboles, espaces) pour la recherche regex."""
    cleaned = re.sub(r"[^\d\s.,\u00a0]", "", text).strip()
    cleaned = cleaned.replace("\u00a0", " ")
    return re.sub(r"\s", " ", cleaned)


def _heuristic_candidates(html: str, url: str) -> list[Candidate]:
    """Collecte les candidats depuis des sélecteurs courants (mode Auto)."""
    soup = _soup(html)
    candidates: list[Candidate] = []
    seen: set[Decimal] = set()
    for selector in _HEURISTIC_SELECTORS:
        if selector.startswith("meta["):
            continue  # traité par extract_opengraph
        for element in soup.select(selector)[:3]:
            text = element.get_text(" ", strip=True)
            if not text or _looks_like_suggestion(text):
                continue
            try:
                price = parse_price(text)
            except ScrapeError:
                continue
            if price in seen:
                continue
            seen.add(price)
            candidates.append(
                Candidate(
                    price=price,
                    strategy=Strategy.CSS,
                    confidence=0.6,
                    source=f"essai CSS {selector!r}",
                )
            )
    return candidates


def _looks_like_suggestion(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _PRICE_STOPWORDS)


def auto_extract(html: str, url: str) -> list[Candidate]:
    """Détection automatique : JSON-LD → OpenGraph → heuristiques CSS → regex.

    Ordre et pondération : JSON-LD est le plus fiable, la regex brute est
    systématiquement en queue (et filtrée ici, elle reste utilisée par le
    Playground comme candidat à part).
    """
    candidates: list[Candidate] = []

    for _currency, price, source in extract_jsonld(html):
        candidates.append(
            Candidate(price=price, strategy=Strategy.JSONLD, confidence=0.92, source=source)
        )

    candidates.extend(extract_opengraph(html, url))
    candidates.extend(_heuristic_candidates(html, url))

    # Dédoublonnage par prix : garde le candidat le plus confiant.
    best_by_price: dict[Decimal, Candidate] = {}
    for candidate in sorted(candidates, key=lambda c: -c.confidence):
        if candidate.price not in best_by_price:
            best_by_price[candidate.price] = candidate
    deduped = list(best_by_price.values())
    return deduped


# ------------------------------------------------------------ validation


def _apply_validation(result: ExtractionResult, validation: Validation | None) -> Decimal:
    best = result.best
    if best is None:
        raise ScrapeError("aucun prix détecté (voir le diagnostic du test)")
    if validation is not None and not validation.validate(best.price):
        raise ScrapeError(
            f"prix {best.price} hors bornes de validation "
            f"({validation.min_price}…{validation.max_price})"
        )
    return best.price


# -------------------------------------------------------------- dispatch


def test_extraction(
    url: str,
    strategy: Strategy | str = Strategy.AUTO,
    *,
    selector: str | None = None,
    xpath: str | None = None,
    regex: str | None = None,
    browser: bool = False,
) -> ExtractionResult:
    """Teste l'extraction sur une URL (Playground / resolver). Ne lève pas :
    renvoie un ExtractionResult (diagnostic + candidats), même en cas d'échec."""
    strategy = Strategy(strategy)
    start = time.perf_counter()
    try:
        if browser or strategy == Strategy.BROWSER:
            html, status = fetch_html_browser(url)
        else:
            html, status = fetch_html(url)
    except ScrapeError as exc:
        return ExtractionResult(url=url, diagnostic=str(exc), status_code=None)
    elapsed = int((time.perf_counter() - start) * 1000)

    try:
        if strategy == Strategy.AUTO:
            candidates = auto_extract(html, url)
        elif strategy == Strategy.JSONLD:
            candidates = [
                Candidate(p, Strategy.JSONLD, 0.92, "JSON-LD")
                for _, p, source in extract_jsonld(html)
            ]
        elif strategy == Strategy.CSS:
            candidates = extract_css(html, selector or "") if selector else []
        elif strategy == Strategy.XPATH:
            candidates = extract_xpath(html, xpath or "") if xpath else []
        elif strategy == Strategy.REGEX:
            candidates = extract_regex(html, regex)
        elif strategy == Strategy.BROWSER:
            candidates = auto_extract(html, url)
        else:  # pragma: no cover
            candidates = []
    except ScrapeError as exc:
        return ExtractionResult(
            url=url,
            candidates=[],
            diagnostic=str(exc),
            status_code=status,
            response_time_ms=elapsed,
            size_bytes=len(html),
        )

    reason = "prix trouvé(s)" if candidates else "aucun prix dans la page"
    return ExtractionResult(
        url=url,
        candidates=candidates,
        diagnostic=reason,
        status_code=status,
        response_time_ms=elapsed,
        size_bytes=len(html),
    )


def scrape_config(config: TrackingConfig) -> Decimal:
    """Prix courant d'un produit configuré. Lève ScrapeError en cas d'échec."""
    result = test_extraction(
        config.url,
        config.strategy,
        selector=config.selector,
        xpath=config.xpath,
        regex=config.regex,
        browser=config.strategy == Strategy.BROWSER,
    )
    if result.best is None:
        raise ScrapeError(f"{config.id} : {result.diagnostic or 'aucun prix détecté'}")
    price = _apply_validation(result, config.validation)
    return price


# --- helpers partagés (imports d'URL, diagnostic) -------------------------


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")
