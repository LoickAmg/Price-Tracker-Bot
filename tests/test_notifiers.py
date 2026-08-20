from decimal import Decimal
from unittest.mock import MagicMock, patch

from price_tracker.history import PriceChange
from price_tracker.notifiers.discord import send_discord_notification
from price_tracker.notifiers.email import send_email_notification

DROP = PriceChange(
    product_id="test-produit",
    name="Produit de test",
    url="https://example.invalid/produit",
    currency="EUR",
    previous=Decimal("10.00"),
    current=Decimal("8.00"),
)


class TestDiscordNotifier:
    def test_returns_false_without_webhook_url(self, monkeypatch):
        monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
        assert send_discord_notification([DROP]) is False

    def test_sends_when_configured(self, monkeypatch):
        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
        mock_response = MagicMock()
        target = "price_tracker.notifiers.discord.requests.post"
        with patch(target, return_value=mock_response) as post:
            assert send_discord_notification([DROP]) is True
        post.assert_called_once()
        assert post.call_args.args[0] == "https://discord.example/webhook"

    def test_network_failure_does_not_raise(self, monkeypatch):
        import requests

        monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
        with patch(
            "price_tracker.notifiers.discord.requests.post",
            side_effect=requests.RequestException("boom"),
        ):
            assert send_discord_notification([DROP]) is False


class TestEmailNotifier:
    def test_returns_false_without_config(self, monkeypatch):
        for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
            monkeypatch.delenv(var, raising=False)
        assert send_email_notification([DROP]) is False

    def test_sends_when_configured(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.invalid")
        monkeypatch.setenv("SMTP_USER", "bot@example.invalid")
        monkeypatch.setenv("SMTP_PASSWORD", "secret")
        monkeypatch.setenv("EMAIL_TO", "me@example.invalid")

        mock_server = MagicMock()
        mock_smtp = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        with patch("price_tracker.notifiers.email.smtplib.SMTP", mock_smtp):
            assert send_email_notification([DROP]) is True
        mock_server.login.assert_called_once_with("bot@example.invalid", "secret")
        mock_server.send_message.assert_called_once()

    def test_smtp_failure_does_not_raise(self, monkeypatch):
        import smtplib

        monkeypatch.setenv("SMTP_HOST", "smtp.example.invalid")
        monkeypatch.setenv("SMTP_USER", "bot@example.invalid")
        monkeypatch.setenv("SMTP_PASSWORD", "secret")
        monkeypatch.setenv("EMAIL_TO", "me@example.invalid")

        with patch(
            "price_tracker.notifiers.email.smtplib.SMTP",
            side_effect=smtplib.SMTPException("boom"),
        ):
            assert send_email_notification([DROP]) is False
