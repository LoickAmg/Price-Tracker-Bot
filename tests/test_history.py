import json
from decimal import Decimal

from price_tracker.config import Product
from price_tracker.history import load_history, save_history, update_history

PRODUCT = Product(
    id="test-produit",
    name="Produit de test",
    url="https://example.invalid/produit",
    selector="p.price",
    currency="EUR",
)


class TestUpdateHistory:
    def test_first_record_creates_entry(self):
        history = {}
        change = update_history(history, PRODUCT, Decimal("10.00"), "2026-01-01T00:00:00Z")

        assert change is not None
        assert change.is_first_record
        assert not change.is_drop
        assert history["test-produit"]["history"] == [
            {"timestamp": "2026-01-01T00:00:00Z", "price": "10.00"}
        ]
        assert history["test-produit"]["last_checked"] == "2026-01-01T00:00:00Z"

    def test_same_price_does_not_append_but_updates_last_checked(self):
        history = {}
        update_history(history, PRODUCT, Decimal("10.00"), "2026-01-01T00:00:00Z")
        change = update_history(history, PRODUCT, Decimal("10.00"), "2026-01-02T00:00:00Z")

        assert change is None
        assert len(history["test-produit"]["history"]) == 1
        assert history["test-produit"]["last_checked"] == "2026-01-02T00:00:00Z"

    def test_price_drop_detected(self):
        history = {}
        update_history(history, PRODUCT, Decimal("10.00"), "2026-01-01T00:00:00Z")
        change = update_history(history, PRODUCT, Decimal("8.00"), "2026-01-02T00:00:00Z")

        assert change is not None
        assert change.is_drop
        assert change.previous == Decimal("10.00")
        assert change.current == Decimal("8.00")

    def test_price_increase_not_a_drop(self):
        history = {}
        update_history(history, PRODUCT, Decimal("10.00"), "2026-01-01T00:00:00Z")
        change = update_history(history, PRODUCT, Decimal("12.00"), "2026-01-02T00:00:00Z")

        assert change is not None
        assert not change.is_drop


class TestPersistence:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "price-history.json"
        history = {}
        update_history(history, PRODUCT, Decimal("10.00"), "2026-01-01T00:00:00Z")

        save_history(path, history)
        loaded = load_history(path)

        assert loaded == history
        # diffs Git lisibles : indenté, pas tout sur une ligne
        assert "\n" in path.read_text(encoding="utf-8")

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_history(tmp_path / "does-not-exist.json") == {}

    def test_save_creates_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "price-history.json"
        save_history(path, {"a": 1})
        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
