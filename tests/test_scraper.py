from decimal import Decimal

import pytest

from price_tracker.scraper import ScrapeError, extract_price, fetch_html, parse_price

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
        assert fetch_html("https://example.test", sleep=seen_delays.append) == "ok"
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


class TestExtractPrice:
    def test_extracts_from_real_looking_fragment(self):
        price = extract_price(BOOKS_TOSCRAPE_FRAGMENT, "p.price_color")
        assert price == Decimal("51.77")

    def test_missing_selector_raises(self):
        with pytest.raises(ScrapeError):
            extract_price(BOOKS_TOSCRAPE_FRAGMENT, "p.does-not-exist")
