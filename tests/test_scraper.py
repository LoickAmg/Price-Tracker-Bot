from decimal import Decimal

import pytest

from price_tracker.scraper import ScrapeError, extract_price, parse_price

# Fragment représentatif du HTML réel de books.toscrape.com (site utilisé
# comme exemple préconfiguré) — évite de dépendre du réseau dans les tests.
BOOKS_TOSCRAPE_FRAGMENT = """
<div class="product_main">
  <h1>A Light in the Attic</h1>
  <p class="price_color">£51.77</p>
  <p class="instock availability">In stock</p>
</div>
"""


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
