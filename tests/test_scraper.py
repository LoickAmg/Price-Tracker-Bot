from decimal import Decimal

import pytest

from price_tracker.config import (
    Strategy,
    TrackingConfig,
    Validation,
)
from price_tracker.scraper import (
    ScrapeError,
    auto_extract,
    extract_css,
    extract_jsonld,
    extract_regex,
    fetch_html,
    fetch_html_browser,
    parse_price,
    scrape_config,
)
from price_tracker.scraper import (
    test_extraction as probe_extraction,
)

# Fragment représentatif du HTML réel de books.toscrape.com (site utilisé
# comme exemple préconfiguré) — évite de dépendre du réseau dans les tests.
BOOKS_TOSCRAPE_FRAGMENT = """
<div class="product_main">
  <h1>A Light in the Attic</h1>
  <p class="price_color">£51.77</p>
  <p class="instock availability">In stock</p>
</div>
"""


class TestFetchHtml:
    def test_retries_connection_error_with_bounded_backoff(self, monkeypatch):
        import requests

        calls = iter([requests.ConnectionError("temporary"), "ok"])
        seen_delays = []

        def fake_get(*args, **kwargs):
            result = next(calls)
            if isinstance(result, Exception):
                raise result
            return type(
                "Response",
                (),
                {
                    "status_code": 200,
                    "text": result,
                    "raise_for_status": lambda self: None,
                },
            )()

        monkeypatch.setattr("price_tracker.scraper.requests.get", fake_get)
        html, status = fetch_html("https://example.test", sleep=seen_delays.append)
        assert html == "ok"
        assert status == 200
        assert seen_delays == [0.5]

    def test_does_not_retry_permanent_http_error(self, monkeypatch):
        import requests

        class Response:
            status_code = 404
            text = ""

            def raise_for_status(self):
                raise requests.HTTPError("not found", response=self)

        calls = []
        monkeypatch.setattr(
            "price_tracker.scraper.requests.get",
            lambda *a, **k: calls.append(1) or Response(),
        )
        with pytest.raises(ScrapeError, match="1 tentative"):
            fetch_html("https://example.test", sleep=lambda _: None)
        assert calls == [1]


class TestParsePrice:
    def test_simple_dot_decimal(self):
        assert parse_price("£51.77") == Decimal("51.77")

    def test_dollar_sign(self):
        assert parse_price("$12.99") == Decimal("12.99")

    def test_european_comma_decimal(self):
        assert parse_price("12,34 €") == Decimal("12.34")

    def test_thousands_dot_decimal_comma(self):
        assert parse_price("1.234,56 €") == Decimal("1234.56")

    def test_thousands_comma_decimal_dot(self):
        assert parse_price("1,234.56") == Decimal("1234.56")

    def test_no_decimals(self):
        assert parse_price("42 €") == Decimal("42")

    def test_no_number_raises(self):
        with pytest.raises(ScrapeError):
            parse_price("indisponible")


class TestExtractCss:
    def test_extracts_from_real_looking_fragment(self):
        candidates = extract_css(BOOKS_TOSCRAPE_FRAGMENT, "p.price_color")
        assert candidates[0].price == Decimal("51.77")
        assert candidates[0].strategy is Strategy.CSS

    def test_missing_selector_raises(self):
        with pytest.raises(ScrapeError):
            extract_css(BOOKS_TOSCRAPE_FRAGMENT, "p.does-not-exist")


JSONLD_FRAGMENT = """
<html><head><script type="application/ld+json">
{"@context":"https://schema.org/","@type":"Product","name":"iPhone 17",
 "offers":{"price":"899.00","priceCurrency":"EUR"}}
</script></head><body></body></html>
"""


class TestExtractJsonLd:
    def test_extracts_price_and_currency(self):
        rows = extract_jsonld(JSONLD_FRAGMENT)
        assert rows == [("EUR", Decimal("899.00"), "JSON-LD")]

    def test_no_json_ld_returns_empty(self):
        assert extract_jsonld("<html><body></body></html>") == []


class TestExtractRegex:
    def test_default_pattern_finds_price_in_html(self):
        fragment = "<p>Prix : <span>12,34 €</span></p>"
        candidates = extract_regex(fragment, None)
        assert any(c.price == Decimal("12.34") for c in candidates)

    def test_custom_pattern(self):
        fragment = "<p>lot de 3 à 45.50 € seulement</p>"
        candidates = extract_regex(fragment, r"\d+\.\d{2}")
        assert any(c.price == Decimal("45.50") for c in candidates)

    def test_no_match_raises(self):
        with pytest.raises(ScrapeError):
            extract_regex("<p>aucun prix</p>", r"\d+\.\d{2}")


class TestAutoExtract:
    def test_jsonld_beats_heuristics(self):
        html = JSONLD_FRAGMENT.replace(
            "</body>",
            """
<p class="price_color">899.00</p></body>
""",
        )
        candidates = auto_extract(html, "https://store.test/p/1")
        best = max(candidates, key=lambda c: (c.confidence, c.strategy.value))
        assert best.strategy is Strategy.JSONLD
        assert best.price == Decimal("899.00")

    def test_empty_html_produces_no_candidates(self):
        assert auto_extract("<html><body></body></html>", "https://x.test/") == []


class TestTestExtraction:
    def test_css_strategy_dispatch(self, monkeypatch):
        monkeypatch.setattr(
            "price_tracker.scraper.fetch_html",
            lambda url, **kw: (BOOKS_TOSCRAPE_FRAGMENT, 200),
        )
        result = probe_extraction("https://x.test/", Strategy.CSS, selector="p.price_color")
        assert result.best is not None
        assert result.best.price == Decimal("51.77")

    def test_failed_fetch_returns_diagnostic_not_exception(self, monkeypatch):
        def boom(url, **kw):
            raise ScrapeError("statut HTTP 500")

        monkeypatch.setattr("price_tracker.scraper.fetch_html", boom)
        result = probe_extraction("https://x.test/")
        assert result.best is None
        assert "statut HTTP 500" in result.diagnostic


class TestBrowser:
    def test_browser_without_playwright_raises_helpful_error(self, monkeypatch):
        def fake_import(name, *a, **k):
            if name.startswith("playwright"):
                raise ImportError("No module named 'playwright'")
            return __import__(name, *a, **k)

        monkeypatch.setattr("builtins.__import__", fake_import)
        with pytest.raises(ScrapeError, match="playwright"):
            fetch_html_browser("https://x.test/")

    def test_browser_strategy_runs_auto_on_rendered_html(self, monkeypatch):
        monkeypatch.setattr(
            "price_tracker.scraper.fetch_html_browser",
            lambda url, **kw: (JSONLD_FRAGMENT, None),
        )
        result = probe_extraction("https://x.test/", Strategy.BROWSER)
        assert result.best is not None
        assert result.best.strategy is Strategy.JSONLD


class TestScrapeConfig:
    def test_validation_rejects_out_of_range_price(self, monkeypatch):
        monkeypatch.setattr(
            "price_tracker.scraper.fetch_html",
            lambda url, **kw: (BOOKS_TOSCRAPE_FRAGMENT, 200),
        )
        config = TrackingConfig(
            id="livre",
            name="Livre",
            url="https://x.test/livre",
            strategy=Strategy.CSS,
            selector="p.price_color",
            validation=Validation(min_price=Decimal("100")),
        )
        with pytest.raises(ScrapeError, match="hors bornes"):
            scrape_config(config)

    def test_ok_price_returned(self, monkeypatch):
        monkeypatch.setattr(
            "price_tracker.scraper.fetch_html",
            lambda url, **kw: (BOOKS_TOSCRAPE_FRAGMENT, 200),
        )
        config = TrackingConfig(
            id="livre",
            name="Livre",
            url="https://x.test/livre",
            strategy=Strategy.CSS,
            selector="p.price_color",
        )
        assert scrape_config(config) == Decimal("51.77")
