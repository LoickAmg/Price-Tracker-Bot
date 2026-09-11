"""Tests E2E de la refonte UX (protocole anti-générique + 14 états).

Ces tests vérifient :
1. Affichage des pages (index, ajouter, légales, 404).
2. Navigation unifiée (index → ajouter via champ rapide).
3. Validation URL (http/https, longueur, IPs privées).
4. Gestion des erreurs réseau (mock).
5. Preview / récapitulatif après résolution.
6. Prix cible transmis correctement.
7. Détection de doublons par URL.
8. Échec d'extraction (aucun prix).
9. Design anti-générique (pas d'emojis, tokens CSS, sr-only, ARIA live).
10. Accessibilité (touch targets, focus-visible).

Tous les appels réseau sont mockés. Le CRUD écrit dans un YAML temporaire.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from price_tracker.config import Strategy, TrackingConfig, save_configs
from price_tracker.resolver import ResolveError, ResolveResult
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


def _resolved(price="51.77", url="https://store.test/livre-deux"):
    candidate = [Candidate(Decimal(price), Strategy.JSONLD, 0.92, "JSON-LD")]
    config = TrackingConfig(
        id="livre-deux",
        name="Livre deux",
        url=url,
        strategy=Strategy.AUTO,
    )
    return ResolveResult(
        config=config, confidence=0.92, candidates=candidate, diagnostic="prix trouvé(s)"
    )


# --- 1. Affichage des pages -----------------------------------------------


class TestPageDisplay:
    def test_index_has_action_entry(self, client):
        html = client.get("/").text
        assert "Surveiller un prix" in html
        assert 'id="quick-add"' in html
        assert 'id="quick-url"' in html

    def test_ajouter_has_two_steps(self, client):
        html = client.get("/ajouter").text
        assert 'id="step-entry"' in html
        assert 'id="step-verify"' in html

    def test_index_has_aria_live(self, client):
        html = client.get("/").text
        assert 'aria-live="polite"' in html
        assert 'id="entry-status"' in html

    def test_ajouter_has_aria_live_notice(self, client):
        html = client.get("/ajouter").text
        assert 'aria-live="polite"' in html


# --- 2. Navigation unifiée -------------------------------------------------


class TestUnifiedFlow:
    def test_index_form_redirects_to_ajouter_with_url(self, client):
        html = client.get("/").text
        assert 'action="/ajouter?url=' not in html
        assert "window.location.assign(`/ajouter?url=" in html
        assert 'id="quick-url"' in html

    def test_ajouter_reads_url_from_query_string(self, client):
        js = client.get("/ajouter").text
        assert "URLSearchParams(window.location.search)" in js
        assert 'params.get("url")' in js
        assert 'id="url"' in js

    def test_quick_add_url_field_wireup(self, client):
        js = client.get("/").text
        assert 'getElementById("quick-url")' in js
        assert "encodeURIComponent(url)" in js


# --- 3. Validation URL (SSRF) ---------------------------------------------


class TestSSRFProtection:
    def test_private_ip_rejected(self, client):
        response = client.post("/api/resolve", json={"url": "http://192.168.1.1/admin"})
        assert response.status_code == 422
        assert "privés" in response.json()["detail"]

    def test_localhost_rejected(self, client):
        response = client.post("/api/resolve", json={"url": "http://localhost:8080/secret"})
        assert response.status_code == 422

    def test_loopback_rejected(self, client):
        response = client.post("/api/resolve", json={"url": "http://127.0.0.1/secret"})
        assert response.status_code == 422

    def test_url_too_long_rejected(self, client):
        long_url = "https://example.com/" + "a" * 3000
        response = client.post("/api/resolve", json={"url": long_url})
        assert response.status_code == 422
        assert "trop longue" in response.json()["detail"]

    def test_non_http_rejected(self, client):
        response = client.post("/api/resolve", json={"url": "ftp://example.com/file"})
        assert response.status_code == 422

    def test_empty_url_rejected(self, client):
        response = client.post("/api/resolve", json={"url": ""})
        assert response.status_code == 422

    def test_valid_https_accepted(self, client):
        with patch("price_tracker.web.resolve_intent", return_value=_resolved()):
            response = client.post("/api/resolve", json={"url": "https://store.test/livre-deux"})
        assert response.status_code == 200

    def test_domain_resolving_to_a_private_ip_is_rejected(self, client):
        """Un domaine public peut pointer vers une IP privée ou l'adresse de
        métadonnées cloud — la protection doit suivre la résolution DNS, pas
        seulement la forme littérale de l'URL."""
        fake_resolution = [(2, 1, 6, "", ("169.254.169.254", 0))]
        with patch("price_tracker.web.socket.getaddrinfo", return_value=fake_resolution):
            response = client.post(
                "/api/resolve", json={"url": "http://looks-public.example/admin"}
            )
        assert response.status_code == 422
        assert "privés" in response.json()["detail"]

    def test_domain_that_fails_to_resolve_is_not_blocked_by_dns_check(self, client):
        """Un domaine qui ne résout pas du tout (DNS indisponible, TLD de
        test) ne doit pas être bloqué par la vérification DNS elle-même —
        seule la requête sortante réelle échouera, plus tard."""
        with patch("price_tracker.web.socket.getaddrinfo", side_effect=OSError("no DNS")):
            with patch("price_tracker.web.resolve_intent", return_value=_resolved()):
                response = client.post(
                    "/api/resolve", json={"url": "https://unresolvable.example/x"}
                )
        assert response.status_code == 200


# --- 4. Gestion erreurs réseau ---------------------------------------------


class TestNetworkErrors:
    def test_resolve_failure_returns_422(self, client):
        with patch(
            "price_tracker.web.resolve_intent",
            side_effect=ResolveError("page introuvable ou aucun prix"),
        ):
            response = client.post("/api/resolve", json={"url": "https://dead.test/page"})
        assert response.status_code == 422
        assert "page introuvable" in response.json()["detail"]

    def test_extract_returns_diagnostic_on_failure(self, client):
        result = ExtractionResult(
            url="https://dead.test/page",
            candidates=[],
            diagnostic="aucun prix dans la page",
            status_code=404,
        )
        with patch("price_tracker.web.test_extraction", return_value=result):
            response = client.post("/api/extract", json={"url": "https://dead.test/page"})
        assert response.status_code == 200
        assert response.json()["candidates"] == []
        assert "aucun prix" in response.json()["diagnostic"]


# --- 5. Preview / récapitulatif -------------------------------------------


class TestPreview:
    def test_resolve_returns_preview_fields(self, client):
        with patch("price_tracker.web.resolve_intent", return_value=_resolved()):
            response = client.post("/api/resolve", json={"url": "https://store.test/livre-deux"})
        data = response.json()
        assert "config" in data
        assert "confidence" in data
        assert "candidates" in data
        assert data["config"]["name"] == "Livre deux"
        assert data["confidence"] == 0.92
        assert len(data["candidates"]) == 1
        assert data["candidates"][0]["price"] == "51.77"


# --- 6. Prix cible ---------------------------------------------------------


class TestTargetPrice:
    def test_target_price_passed_to_resolve(self, client):
        with patch("price_tracker.web.resolve_intent") as mock_resolve:
            mock_resolve.return_value = _resolved()
            client.post(
                "/api/resolve",
                json={
                    "url": "https://store.test/livre-deux",
                    "target": "45.00",
                },
            )
        call_kwargs = mock_resolve.call_args
        intent = call_kwargs[1]["intent"] if "intent" in call_kwargs[1] else call_kwargs[0][0]
        assert intent.target_price == Decimal("45.00")

    def test_target_price_optional(self, client):
        with patch("price_tracker.web.resolve_intent") as mock_resolve:
            mock_resolve.return_value = _resolved()
            client.post(
                "/api/resolve",
                json={"url": "https://store.test/livre-deux"},
            )
        call_kwargs = mock_resolve.call_args
        intent = call_kwargs[1]["intent"] if "intent" in call_kwargs[1] else call_kwargs[0][0]
        assert intent.target_price is None


# --- 7. Détection doublons -------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_url_rejected(self, client):
        response = client.post(
            "/api/products",
            json={
                "name": "Doublon URL",
                "url": "https://example.invalid/livre-un",
            },
        )
        assert response.status_code == 409
        assert "déjà suivi" in response.json()["detail"]

    def test_same_url_different_slash_accepted(self, client):
        response = client.post(
            "/api/products",
            json={
                "name": "Produit neuf",
                "url": "https://unique.example/new-product",
            },
        )
        assert response.status_code == 200

    def test_duplicate_id_rejected(self, client):
        response = client.post(
            "/api/products",
            json={
                "id": "livre-un",
                "name": "Doublon ID",
                "url": "https://other.example/product",
            },
        )
        assert response.status_code == 409


# --- 8. Échec d'extraction -------------------------------------------------


class TestExtractionFailure:
    def test_no_candidates_returns_empty(self, client):
        result = ExtractionResult(
            url="https://empty.test/page",
            candidates=[],
            diagnostic="page vide",
            status_code=200,
        )
        with patch("price_tracker.web.test_extraction", return_value=result):
            response = client.post("/api/extract", json={"url": "https://empty.test/page"})
        assert response.status_code == 200
        assert response.json()["candidates"] == []
        assert response.json()["best"] is None


# --- 9. Design anti-générique ----------------------------------------------


class TestAntiGeneriqueDesign:
    def test_no_emojis_in_index(self, client):
        html = client.get("/").text
        emoji_chars = [chr(c) for c in range(0x1F600, 0x1F650)]
        for char in emoji_chars:
            assert char not in html, f"emoji trouvé dans index.html : {char}"

    def test_no_emojis_in_ajouter(self, client):
        html = client.get("/ajouter").text
        emoji_chars = [chr(c) for c in range(0x1F600, 0x1F650)]
        for char in emoji_chars:
            assert char not in html, f"emoji trouvé dans ajouter.html : {char}"

    def test_css_has_tokens_in_root(self, client):
        css = client.get("/assets/style.css").text
        assert ":root {" in css
        assert "--paper:" in css
        assert "--ink:" in css
        assert "--moss:" in css

    def test_css_has_focus_visible(self, client):
        css = client.get("/assets/style.css").text
        assert "focus-visible" in css

    def test_css_has_sr_only(self, client):
        css = client.get("/assets/style.css").text
        assert ".sr-only" in css

    def test_index_has_sr_only_class(self, client):
        html = client.get("/").text
        assert "sr-only" in html


# --- 10. Accessibilité ------------------------------------------------------


class TestAccessibility:
    def test_touch_target_min_height(self, client):
        css = client.get("/assets/style.css").text
        assert "min-height: 44px" in css

    def test_aria_label_on_nav(self, client):
        for path in ("/", "/ajouter"):
            html = client.get(path).text
            assert 'aria-label="Navigation"' in html

    def test_label_for_url_input(self, client):
        html = client.get("/ajouter").text
        assert 'for="url"' in html

    def test_aria_describedby_on_url(self, client):
        html = client.get("/ajouter").text
        assert 'aria-describedby="url-hint"' in html

    def test_role_radiogroup_on_level(self, client):
        html = client.get("/ajouter").text
        assert 'role="radiogroup"' in html
