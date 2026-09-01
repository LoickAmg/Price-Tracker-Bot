"""Tests d'intégration de la web app (TestClient FastAPI, hors réseau).

Les appels réseau (resolver/extraction) sont remplacés par des faux propres au
traitement HTTP ; le CRUD écrit dans un products.yaml temporaire.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from price_tracker.config import Strategy, TrackingConfig, save_configs
from price_tracker.resolver import ResolveResult
from price_tracker.scraper import Candidate, ExtractionResult
from price_tracker.web import create_app


@pytest.fixture
def client(tmp_path):
    config = tmp_path / "products.yaml"
    history = tmp_path / "price-history.json"
    bank = tmp_path / "bank.json"
    save_configs(
        config,
        [
            TrackingConfig(
                id="livre-un",
                name="Un livre",
                url="https://example.invalid/livre-un",
                strategy=Strategy.CSS,
                selector="p.price",
            )
        ],
    )
    app = create_app(config, history, bank)
    with TestClient(app) as tc:
        yield tc


def resolved_payload(price="51.77"):
    candidate = [Candidate(Decimal(price), Strategy.JSONLD, 0.92, "JSON-LD")]
    config = TrackingConfig(
        id="livre-deux",
        name="Livre deux",
        url="https://store.test/livre-deux",
        strategy=Strategy.AUTO,
    )
    result = ResolveResult(
        config=config, confidence=0.92, candidates=candidate, diagnostic="prix trouvé(s)"
    )
    return result


class TestPages:
    def test_home_serves_dashboard(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Suivi de prix" in response.text

    def test_ajouter_page(self, client):
        response = client.get("/ajouter")
        assert response.status_code == 200
        assert "Ajouter un produit" in response.text

    def test_legal_pages(self, client):
        for path in ("/mentions-legales", "/confidentialite", "/contact"):
            response = client.get(path)
            assert response.status_code == 200, path

    def test_missing_page_returns_404(self, client):
        assert client.get("/n-existe-pas").status_code == 404

    def test_assets(self, client):
        for path in ("/assets/style.css", "/assets/app.js"):
            assert client.get(path).status_code == 200, path


class TestApiHealth:
    def test_health(self, client):
        assert client.get("/api/health").json() == {"ok": True}


class TestApiProducts:
    def test_lists_configured_products(self, client):
        payload = client.get("/api/products").json()
        assert len(payload["products"]) == 1
        assert payload["products"][0]["id"] == "livre-un"

    def test_create_and_delete(self, client):
        response = client.post(
            "/api/products",
            json={
                "id": "nouveau",
                "name": "Nouveau",
                "url": "https://store.test/nouveau",
                "strategy": "jsonld",
                "level": "expert",
                "currency": "EUR",
                "alert": {"mode": "price_below", "threshold": "80"},
                "interval_hours": 12,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["id"] == "nouveau"

        listed = client.get("/api/products").json()
        assert {entry["id"] for entry in listed["products"]} == {"livre-un", "nouveau"}

        deleted = client.delete("/api/products/nouveau")
        assert deleted.status_code == 200
        assert "nouveau" not in {
            entry["id"] for entry in client.get("/api/products").json()["products"]
        }

    def test_duplicate_id_rejected(self, client):
        response = client.post(
            "/api/products",
            json={
                "id": "livre-un",
                "name": "Doublon",
                "url": "https://store.test/doublon",
                "strategy": "auto",
            },
        )
        assert response.status_code == 409

    def test_invalid_payload_rejected(self, client):
        response = client.post(
            "/api/products",
            json={"id": "x", "name": "X", "url": "pas-une-url", "strategy": "auto"},
        )
        assert response.status_code == 422

    def test_history_endpoint(self, client):
        response = client.get("/api/products/livre-un/history")
        assert response.status_code == 200
        assert response.json()["history"] == []


class TestApiResolve:
    def test_resolves_intent(self, client):
        with patch("price_tracker.web.resolve_intent", return_value=resolved_payload()):
            response = client.post("/api/resolve", json={"url": "https://store.test/livre-deux"})
        assert response.status_code == 200
        outcome = response.json()
        assert outcome["config"]["id"] == "livre-deux"
        assert outcome["confidence"] == 0.92
        assert outcome["candidates"][0]["price"] == "51.77"

    def test_bad_url_rejected(self, client):
        response = client.post("/api/resolve", json={"url": "nimporte quoi"})
        assert response.status_code == 422

    def test_resolve_failure_reported(self, client):
        from price_tracker.resolver import ResolveError

        with patch(
            "price_tracker.web.resolve_intent",
            side_effect=ResolveError("aucun prix dans la page"),
        ):
            response = client.post("/api/resolve", json={"url": "https://store.test/x"})
        assert response.status_code == 422
        assert "aucun prix" in response.json()["detail"]


class TestApiExtract:
    def test_extract_playground(self, client):
        result = ExtractionResult(
            url="https://store.test/livre-deux",
            candidates=[Candidate(Decimal("12.34"), Strategy.CSS, 0.95, "CSS p.price")],
            diagnostic="prix trouvé(s)",
            status_code=200,
        )
        with patch("price_tracker.web.test_extraction", return_value=result):
            response = client.post(
                "/api/extract",
                json={
                    "url": "https://store.test/livre-deux",
                    "strategy": "css",
                    "selector": "p.price",
                },
            )
        assert response.status_code == 200
        assert response.json()["best"]["price"] == "12.34"
        assert response.json()["status_code"] == 200

    def test_bad_strategy_rejected(self, client):
        response = client.post("/api/extract", json={"url": "https://x.test/", "strategy": "jdr"})
        assert response.status_code == 422
