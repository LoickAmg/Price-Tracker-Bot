import pytest

from price_tracker.config import ConfigError, load_products


def write_config(tmp_path, content):
    path = tmp_path / "products.yaml"
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadProducts:
    def test_loads_valid_config(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            products:
              - id: livre-un
                name: Un livre
                url: https://example.invalid/livre-un
                selector: p.price
                currency: EUR
            """,
        )
        products = load_products(path)
        assert len(products) == 1
        assert products[0].id == "livre-un"
        assert products[0].currency == "EUR"

    def test_defaults_name_to_id_and_currency_to_eur(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            products:
              - id: livre-un
                url: https://example.invalid/livre-un
                selector: p.price
            """,
        )
        products = load_products(path)
        assert products[0].name == "livre-un"
        assert products[0].currency == "EUR"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigError):
            load_products(tmp_path / "does-not-exist.yaml")

    def test_empty_products_list_raises(self, tmp_path):
        path = write_config(tmp_path, "products: []")
        with pytest.raises(ConfigError):
            load_products(path)

    def test_missing_required_field_raises(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            products:
              - id: livre-un
                url: https://example.invalid/livre-un
            """,
        )
        with pytest.raises(ConfigError):
            load_products(path)

    def test_duplicate_id_raises(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            products:
              - id: livre-un
                url: https://example.invalid/a
                selector: p.price
              - id: livre-un
                url: https://example.invalid/b
                selector: p.price
            """,
        )
        with pytest.raises(ConfigError):
            load_products(path)

    def test_invalid_url_raises(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            products:
              - id: livre-un
                url: pas-une-url
                selector: p.price
            """,
        )
        with pytest.raises(ConfigError):
            load_products(path)
