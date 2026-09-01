import pytest

from price_tracker.config import (
    AlertMode,
    AlertRule,
    ConfigError,
    Level,
    Strategy,
    TrackingConfig,
    Validation,
    load_configs,
    load_products,
    save_configs,
)


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

    def test_v1_selector_is_mounted_as_css_strategy(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            products:
              - id: livre-un
                url: https://example.invalid/livre-un
                selector: p.price
            """,
        )
        (product,) = load_configs(path)
        assert product.strategy is Strategy.CSS
        assert product.selector == "p.price"
        assert product.level is Level.AUTO

    def test_v2_strategy_and_alert_parsed(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            products:
              - id: airpods
                name: AirPods Pro
                url: https://example.invalid/airpods
                level: expert
                strategy: jsonld
                currency: EUR
                validation:
                  min: "50"
                  max: "400"
                alert:
                  mode: price_below
                  threshold: "200"
            """,
        )
        (product,) = load_configs(path)
        assert product.strategy is Strategy.JSONLD
        assert product.level is Level.EXPERT
        assert product.validation.min_price is not None
        assert product.alert.mode is AlertMode.PRICE_BELOW
        assert str(product.alert.threshold) == "200"

    def test_unknown_strategy_raises(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            products:
              - id: livre-un
                url: https://example.invalid/a
                strategy: télépathie
            """,
        )
        with pytest.raises(ConfigError, match="stratégie"):
            load_configs(path)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigError):
            load_products(tmp_path / "does-not-exist.yaml")

    def test_empty_products_list_raises(self, tmp_path):
        path = write_config(tmp_path, "products: []")
        with pytest.raises(ConfigError):
            load_products(path)

    def test_minimal_config_valid_with_id_and_url(self, tmp_path):
        path = write_config(
            tmp_path,
            """
            products:
              - id: livre-un
                url: https://example.invalid/livre-un
            """,
        )
        (product,) = load_configs(path)
        assert product.id == "livre-un"
        assert product.strategy is Strategy.AUTO

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


class TestSaveRoundTrip:
    def test_save_then_load_keeps_fields(self, tmp_path):
        path = tmp_path / "products.yaml"
        configs = [
            TrackingConfig(
                id="livre-un",
                name="Un livre",
                url="https://example.invalid/livre-un",
                strategy=Strategy.JSONLD,
                level=Level.CUSTOM,
                validation=Validation(min_price=10, max_price=200),
                alert=AlertRule(mode=AlertMode.PRICE_BELOW, threshold=150),
                confidence=0.9,
                domain="example.invalid",
            )
        ]
        save_configs(path, configs)
        loaded = load_configs(path)
        assert loaded == configs

    def test_writes_id_and_url_first_for_readable_diffs(self, tmp_path):
        path = tmp_path / "products.yaml"
        save_configs(path, [TrackingConfig(id="a", name="A", url="https://x.test/a")])
        text = path.read_text(encoding="utf-8")
        assert "- id: a" in text
        # id précède url dans l'entrée : diffs Git lisibles.
        assert text.index("- id: a") < text.index("url: https://x.test/a")

    def test_preserves_existing_header_comments(self, tmp_path):
        path = tmp_path / "products.yaml"
        path.write_text("# Mon en-tête perso\n# deuxième ligne\n\nproducts: []", encoding="utf-8")
        save_configs(path, [TrackingConfig(id="a", name="A", url="https://x.test/a")])
        text = path.read_text(encoding="utf-8")
        assert "Mon en-tête perso" in text
        assert "deuxième ligne" in text


class TestTrackingConfigValidation:
    def test_invalid_id_raises(self):
        with pytest.raises(ConfigError):
            TrackingConfig(id="avec un espace", name="X", url="https://x.test/")

    def test_invalid_url_raises(self):
        with pytest.raises(ConfigError):
            TrackingConfig(id="a", name="X", url="ftp://x.test/")

    def test_invalid_interval_raises(self):
        with pytest.raises(ConfigError):
            TrackingConfig(id="a", name="X", url="https://x.test/", interval_hours=0)
