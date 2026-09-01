from decimal import Decimal

import pytest

from price_tracker.config import Level, ProductIntent, Strategy
from price_tracker.resolver import ResolveError, StrategyBank, resolve_intent
from price_tracker.scraper import Candidate


def fake_extraction(url, strategy, **kwargs):
    candidates = [Candidate(Decimal("899.00"), Strategy.JSONLD, 0.92, "JSON-LD")]
    return type("R", (), {"candidates": candidates, "diagnostic": "ok", "best": candidates[0]})()


def stub_network(monkeypatch):
    monkeypatch.setattr("price_tracker.resolver.test_extraction", fake_extraction)


class TestSlugify:
    def test_basic_slug(self):
        from price_tracker.resolver import slugify

        assert slugify("iPhone 17") == "iphone-17"

    def test_collapses_separators(self):
        from price_tracker.resolver import slugify

        assert slugify("Sony · WH-1000XM6") == "sony-wh-1000xm6"


class TestResolveIntent:
    def test_auto_level_leaves_engine_in_auto(self, monkeypatch):
        stub_network(monkeypatch)
        result = resolve_intent(
            ProductIntent(url="https://store.test/iphone-17", target_price=Decimal("800")),
            existing_ids=set(),
        )
        assert result.config.strategy is Strategy.AUTO
        assert result.confidence == 0.92
        assert str(result.config.alert.threshold) == "800"
        assert result.config.domain == "store.test"

    def test_expert_level_locks_strategy(self, monkeypatch):
        stub_network(monkeypatch)
        result = resolve_intent(
            ProductIntent(url="https://store.test/iphone-17", level=Level.EXPERT),
            existing_ids=set(),
        )
        assert result.config.strategy is Strategy.JSONLD

    def test_generates_unique_id(self, monkeypatch):
        stub_network(monkeypatch)
        result = resolve_intent(
            ProductIntent(query="iPhone 17", url="https://store.test/iphone-17"),
            existing_ids={"iphone-17"},
        )
        assert result.config.id == "iphone-17-1"

    def test_without_url_raises(self, monkeypatch):
        with pytest.raises(ResolveError):
            resolve_intent(ProductIntent(query="AirPods sous 200 €"), existing_ids=set())

    def test_failed_extraction_raises_with_diagnostic(self, monkeypatch):
        def failed(url, strategy, **kwargs):
            return type(
                "R",
                (),
                {"candidates": [], "diagnostic": "aucun prix dans la page", "best": None},
            )()

        monkeypatch.setattr("price_tracker.resolver.test_extraction", failed)
        with pytest.raises(ResolveError, match="aucun prix"):
            resolve_intent(ProductIntent(url="https://store.test/x"), existing_ids=set())


class TestStrategyBank:
    def test_remembers_and_prefers_domain_strategy(self, tmp_path, monkeypatch):
        stub_network(monkeypatch)
        bank = StrategyBank(tmp_path / "bank.json")
        resolve_intent(
            ProductIntent(url="https://store.test/iphone-17"),
            existing_ids=set(),
            bank=bank,
        )
        assert bank.preferred("store.test") is Strategy.JSONLD

    def test_preferred_is_used_for_second_resolution(self, tmp_path, monkeypatch):
        bank = StrategyBank(tmp_path / "bank.json")

        def spy(url, strategy, **kwargs):
            strategies_used.append(strategy)
            return fake_extraction(url, strategy, **kwargs)

        strategies_used = []
        monkeypatch.setattr("price_tracker.resolver.test_extraction", spy)
        resolve_intent(ProductIntent(url="https://store.test/a"), existing_ids=set(), bank=bank)
        resolve_intent(ProductIntent(url="https://store.test/b"), existing_ids=set(), bank=bank)
        assert strategies_used[1] is Strategy.JSONLD

    def test_missing_file_returns_none(self, tmp_path):
        bank = StrategyBank(tmp_path / "absent.json")
        assert bank.preferred("example.test") is None
