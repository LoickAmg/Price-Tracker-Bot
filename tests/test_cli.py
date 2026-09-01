from decimal import Decimal
from unittest.mock import patch

from price_tracker.cli import run
from price_tracker.config import Level, Strategy, TrackingConfig
from price_tracker.resolver import ResolveResult
from price_tracker.scraper import ScrapeError


def write_config(tmp_path):
    path = tmp_path / "products.yaml"
    path.write_text(
        """
        products:
          - id: livre-un
            name: Un livre
            url: https://example.invalid/livre-un
            selector: p.price
            currency: EUR
        """,
        encoding="utf-8",
    )
    return path


class TestRun:
    def test_dry_run_does_not_write_history(self, tmp_path):
        config = write_config(tmp_path)
        history = tmp_path / "price-history.json"

        with patch("price_tracker.cli.scrape_config", return_value=Decimal("10.00")):
            exit_code = run(["--config", str(config), "--history", str(history), "--dry-run"])

        assert exit_code == 0
        assert not history.exists()

    def test_writes_history_on_success(self, tmp_path):
        config = write_config(tmp_path)
        history = tmp_path / "price-history.json"

        with patch("price_tracker.cli.scrape_config", return_value=Decimal("10.00")):
            exit_code = run(["--config", str(config), "--history", str(history)])

        assert exit_code == 0
        assert history.exists()
        assert "livre-un" in history.read_text(encoding="utf-8")

    def test_drop_triggers_notify_all(self, tmp_path):
        config = write_config(tmp_path)
        history_path = tmp_path / "price-history.json"

        with patch("price_tracker.cli.scrape_config", return_value=Decimal("10.00")):
            run(["--config", str(config), "--history", str(history_path)])

        with (
            patch("price_tracker.cli.scrape_config", return_value=Decimal("8.00")),
            patch("price_tracker.cli.notify_all") as mock_notify,
        ):
            run(["--config", str(config), "--history", str(history_path)])

        mock_notify.assert_called_once()
        drops = mock_notify.call_args.args[0]
        assert len(drops) == 1
        assert drops[0].current == Decimal("8.00")

    def test_all_products_failing_returns_error_code(self, tmp_path):
        config = write_config(tmp_path)
        history = tmp_path / "price-history.json"

        with patch("price_tracker.cli.scrape_config", side_effect=ScrapeError("boom")):
            exit_code = run(["--config", str(config), "--history", str(history)])

        assert exit_code == 1

    def test_invalid_config_returns_error_code(self, tmp_path):
        exit_code = run(["--config", str(tmp_path / "missing.yaml")])
        assert exit_code == 1


def make_resolved(url="https://store.test/p"):
    candidate = ResolveResult(
        config=TrackingConfig(
            id="iphone-17",
            name="iphone-17",
            url=url,
            level=Level.AUTO,
            strategy=Strategy.AUTO,
            domain="store.test",
        ),
        confidence=0.92,
        candidates=[],
        diagnostic="ok",
    )
    return candidate


class TestAdd:
    def test_dry_run_does_not_write_products_yaml(self, tmp_path):
        config = tmp_path / "products.yaml"
        with patch("price_tracker.cli.resolve_intent", return_value=make_resolved()):
            exit_code = run(["add", "https://store.test/p", "--dry-run"])

        assert exit_code == 0
        assert not config.exists()

    def test_add_writes_config_and_id(self, tmp_path):
        config = tmp_path / "products.yaml"
        with patch("price_tracker.cli.resolve_intent", return_value=make_resolved()):
            exit_code = run(["add", "https://store.test/p", "--config", str(config)])

        assert exit_code == 0
        assert "iphone-17" in config.read_text(encoding="utf-8")

    def test_add_locks_strategy_when_requested(self, tmp_path):
        config = tmp_path / "products.yaml"
        with patch("price_tracker.cli.resolve_intent", return_value=make_resolved()):
            run(["add", "https://store.test/p", "--strategy", "jsonld", "--config", str(config)])

        text = config.read_text(encoding="utf-8")
        assert "strategy: jsonld" in text

    def test_add_bad_target_returns_error(self, tmp_path):
        with patch("price_tracker.cli.resolve_intent", return_value=make_resolved()):
            exit_code = run(["add", "https://store.test/p", "--target", "abc"])
        assert exit_code == 1

    def test_add_resolve_failure_returns_error(self, tmp_path):
        from price_tracker.resolver import ResolveError

        with patch("price_tracker.cli.resolve_intent", side_effect=ResolveError("aucun prix")):
            exit_code = run(["add", "https://store.test/p"])
        assert exit_code == 1


class TestTest:
    def test_test_subcommand_prints_candidates(self, tmp_path, capsys):
        from price_tracker.scraper import Candidate, ExtractionResult

        result = ExtractionResult(
            url="https://store.test/p",
            candidates=[Candidate(Decimal("899.00"), Strategy.JSONLD, 0.92, "JSON-LD")],
            diagnostic="prix trouvé(s)",
        )
        with patch("price_tracker.cli.test_extraction", return_value=result):
            exit_code = run(["test", "https://store.test/p"])

        out = capsys.readouterr().out
        assert "899.00" in out
        assert exit_code == 0

    def test_test_no_candidates_returns_error(self, tmp_path, capsys):
        from price_tracker.scraper import ExtractionResult

        result = ExtractionResult(
            url="https://store.test/p", candidates=[], diagnostic="aucun prix"
        )
        with patch("price_tracker.cli.test_extraction", return_value=result):
            exit_code = run(["test", "https://store.test/p"])

        assert exit_code == 1
        assert "aucun prix" in capsys.readouterr().out
