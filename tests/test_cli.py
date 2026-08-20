from decimal import Decimal
from unittest.mock import patch

from price_tracker.cli import run


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

        with patch("price_tracker.cli.scrape_price", return_value=Decimal("10.00")):
            exit_code = run(["--config", str(config), "--history", str(history), "--dry-run"])

        assert exit_code == 0
        assert not history.exists()

    def test_writes_history_on_success(self, tmp_path):
        config = write_config(tmp_path)
        history = tmp_path / "price-history.json"

        with patch("price_tracker.cli.scrape_price", return_value=Decimal("10.00")):
            exit_code = run(["--config", str(config), "--history", str(history)])

        assert exit_code == 0
        assert history.exists()
        assert "livre-un" in history.read_text(encoding="utf-8")

    def test_drop_triggers_notify_all(self, tmp_path):
        config = write_config(tmp_path)
        history_path = tmp_path / "price-history.json"

        with patch("price_tracker.cli.scrape_price", return_value=Decimal("10.00")):
            run(["--config", str(config), "--history", str(history_path)])

        with (
            patch("price_tracker.cli.scrape_price", return_value=Decimal("8.00")),
            patch("price_tracker.cli.notify_all") as mock_notify,
        ):
            run(["--config", str(config), "--history", str(history_path)])

        mock_notify.assert_called_once()
        drops = mock_notify.call_args.args[0]
        assert len(drops) == 1
        assert drops[0].current == Decimal("8.00")

    def test_all_products_failing_returns_error_code(self, tmp_path):
        from price_tracker.scraper import ScrapeError

        config = write_config(tmp_path)
        history = tmp_path / "price-history.json"

        with patch("price_tracker.cli.scrape_price", side_effect=ScrapeError("boom")):
            exit_code = run(["--config", str(config), "--history", str(history)])

        assert exit_code == 1

    def test_invalid_config_returns_error_code(self, tmp_path):
        exit_code = run(["--config", str(tmp_path / "missing.yaml")])
        assert exit_code == 1
