"""Web app FastAPI V2 : tableau de bord + écran « Ajouter un produit ».

Routes :
- pages  : / (dashboard), /ajouter (Ajouter un produit), pages légales, 404.
- API    : /api/resolve (intention → config testée), /api/extract (Playground),
           /api/products (CRUD sur products.yaml), /api/products/{id}/history.

Politique d'écriture : tout ce qui crée une TrackingConfig passe par le YAML ;
rien n'est écrit sans validation (mêmes règles que le CLI).
"""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from price_tracker.config import (
    AlertMode,
    AlertRule,
    ConfigError,
    Level,
    ProductIntent,
    Strategy,
    TrackingConfig,
    Validation,
    load_configs,
    save_configs,
)
from price_tracker.history import load_history
from price_tracker.resolver import ResolveError, StrategyBank, resolve_intent
from price_tracker.scraper import test_extraction

DEFAULT_CONFIG_PATH = Path("products.yaml")
DEFAULT_HISTORY_PATH = Path("docs/data/price-history.json")
DEFAULT_BANK_PATH = Path("strategy-bank.json")
WEB_DIR = Path(
    os.environ.get(
        "PT_WEB_DIR",
        Path(__file__).resolve().parent.parent.parent / "web",
    )
)

_LEVELS = {"auto": Level.AUTO, "custom": Level.CUSTOM, "expert": Level.EXPERT}
_ALERTS = {
    "price_below": AlertMode.PRICE_BELOW,
    "drop_pct": AlertMode.DROP_PCT,
    "any_change": AlertMode.ANY_CHANGE,
}


def _to_decimal(value, field: str) -> Decimal | None:
    if value in (None, "", "null"):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise HTTPException(422, f"{field} : valeur décimale invalide {value!r}") from exc


def _config_dict(config: TrackingConfig) -> dict:
    return config.to_dict()


def _product_view(config: TrackingConfig, history) -> dict:
    entry = history.get(config.id)
    history_points = (entry.get("history") or []) if entry else []
    latest = history_points[-1]["price"] if history_points else None
    return {
        **_config_dict(config),
        "latest_price": latest,
        "last_checked": entry.get("last_checked") if entry else None,
        "history_points": history_points,
    }


def create_app(
    config_path: Path = DEFAULT_CONFIG_PATH,
    history_path: Path = DEFAULT_HISTORY_PATH,
    bank_path: Path = DEFAULT_BANK_PATH,
) -> FastAPI:
    app = FastAPI(title="Price Tracker V2", version="0.2.0")

    if WEB_DIR.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

    def _read_configs() -> list[TrackingConfig]:
        if not config_path.exists():
            return []
        try:
            return load_configs(config_path)
        except ConfigError as exc:
            raise HTTPException(500, f"products.yaml invalide : {exc}") from exc

    def _save_configs(configs: list[TrackingConfig]) -> None:
        save_configs(config_path, configs)

    # ------------------------------------------------------------- pages

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/ajouter", response_class=HTMLResponse, include_in_schema=False)
    def add_page() -> FileResponse:
        return FileResponse(WEB_DIR / "ajouter.html")

    @app.get("/mentions-legales", response_class=HTMLResponse, include_in_schema=False)
    def mentions() -> FileResponse:
        return FileResponse(WEB_DIR / "mentions-legales.html")

    @app.get("/confidentialite", response_class=HTMLResponse, include_in_schema=False)
    def confidentialite() -> FileResponse:
        return FileResponse(WEB_DIR / "confidentialite.html")

    @app.get("/contact", response_class=HTMLResponse, include_in_schema=False)
    def contact() -> FileResponse:
        return FileResponse(WEB_DIR / "contact.html")

    @app.exception_handler(404)
    async def not_found(request: Request, _exc) -> Response:
        if request.url.path.startswith("/api/"):
            return JSONResponse(status_code=404, content={"detail": "Page introuvable"})
        page = WEB_DIR / "404.html"
        body = page.read_text(encoding="utf-8") if page.exists() else "404"
        return HTMLResponse(body, status_code=404)

    # ---------------------------------------------------------------- API

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/resolve")
    def api_resolve(body: dict) -> JSONResponse:
        url = str(body.get("url") or "")
        if not url.startswith(("http://", "https://")):
            raise HTTPException(422, "url manquante ou invalide")

        target = _to_decimal(body.get("target"), "target")
        level = _LEVELS.get(str(body.get("level") or "auto"), Level.AUTO)
        query = str(body.get("query") or "")

        intent = ProductIntent(
            query=query,
            url=url,
            target_price=target,
            alert_mode=AlertMode.PRICE_BELOW,
            level=level,
        )
        bank = StrategyBank(bank_path)
        existing_ids = {c.id for c in _read_configs()}
        try:
            resolved = resolve_intent(intent, existing_ids=existing_ids, bank=bank)
        except ResolveError as exc:
            raise HTTPException(422, str(exc)) from exc

        candidates = [
            {
                "price": str(c.price),
                "strategy": c.strategy.value,
                "confidence": c.confidence,
                "source": c.source,
            }
            for c in resolved.candidates
        ]
        return {
            "config": _config_dict(resolved.config),
            "confidence": resolved.confidence,
            "candidates": candidates,
            "diagnostic": resolved.diagnostic,
        }

    @app.post("/api/extract")
    def api_extract(body: dict) -> dict:
        url = str(body.get("url") or "")
        if not url.startswith(("http://", "https://")):
            raise HTTPException(422, "url manquante ou invalide")
        try:
            strategy = Strategy(str(body.get("strategy") or "auto"))
        except ValueError as exc:
            raise HTTPException(422, f"stratégie inconnue : {body.get('strategy')!r}") from exc

        result = test_extraction(
            url,
            strategy,
            selector=body.get("selector") or None,
            xpath=body.get("xpath") or None,
            regex=body.get("regex") or None,
            browser=bool(body.get("browser", False)),
        )
        return {
            "url": result.url,
            "status_code": result.status_code,
            "response_time_ms": result.response_time_ms,
            "size_bytes": result.size_bytes,
            "diagnostic": result.diagnostic,
            "candidates": [
                {
                    "price": str(c.price),
                    "strategy": c.strategy.value,
                    "confidence": c.confidence,
                    "source": c.source,
                }
                for c in result.candidates
            ],
            "best": (
                {"price": str(result.best.price), "strategy": result.best.strategy.value}
                if result.best
                else None
            ),
        }

    @app.get("/api/products")
    def api_products() -> dict:
        configs = _read_configs()
        history = load_history(history_path)
        return {"products": [_product_view(c, history) for c in configs]}

    @app.get("/api/products/{product_id}/history")
    def api_product_history(product_id: str) -> dict:
        configs = _read_configs()
        config = next((c for c in configs if c.id == product_id), None)
        if config is None:
            raise HTTPException(404, f"produit inconnu : {product_id}")
        history = load_history(history_path)
        entry = history.get(product_id)
        return {
            **_config_dict(config),
            "history": (entry or {"history": []})["history"],
            "last_checked": entry.get("last_checked") if entry else None,
        }

    @app.post("/api/products")
    def api_create_product(body: dict) -> dict:
        configs = _read_configs()
        product_id = str(body.get("id") or "").strip()
        if existing := _find(configs, product_id):
            raise HTTPException(409, f"id déjà utilisé : {existing.id}")

        try:
            strategy = Strategy(str(body.get("strategy") or "auto"))
            level = _LEVELS.get(str(body.get("level") or "auto"), Level.AUTO)
            alert_mode = _ALERTS.get(str((body.get("alert") or {}).get("mode") or "price_below"))
            config = TrackingConfig(
                id=product_id or _next_id(configs, str(body.get("url") or "produit")),
                name=str(body.get("name") or product_id or "produit"),
                url=str(body.get("url") or ""),
                level=level,
                strategy=strategy,
                currency=str(body.get("currency") or "EUR"),
                selector=str(body["selector"]) if body.get("selector") else None,
                xpath=str(body["xpath"]) if body.get("xpath") else None,
                regex=str(body["regex"]) if body.get("regex") else None,
                validation=Validation(
                    min_price=_to_decimal(body.get("min_price"), "min_price"),
                    max_price=_to_decimal(body.get("max_price"), "max_price"),
                ),
                alert=AlertRule(
                    mode=alert_mode,
                    threshold=_to_decimal((body.get("alert") or {}).get("threshold"), "threshold"),
                ),
                interval_hours=int(body.get("interval_hours") or 6),
            )
        except ConfigError as exc:
            raise HTTPException(422, str(exc)) from exc

        configs.append(config)
        _save_configs(configs)
        return _config_dict(config)

    @app.delete("/api/products/{product_id}")
    def api_delete_product(product_id: str) -> dict:
        configs = _read_configs()
        remaining = [c for c in configs if c.id != product_id]
        if len(remaining) == len(configs):
            raise HTTPException(404, f"produit inconnu : {product_id}")
        _save_configs(remaining)
        return {"deleted": product_id}

    return app


def _find(configs: list[TrackingConfig], product_id: str) -> TrackingConfig | None:
    return next((c for c in configs if c.id == product_id), None)


def _next_id(configs: list[TrackingConfig], seed: str) -> str:
    from price_tracker.resolver import slugify

    base = slugify(seed.removeprefix("https://").removeprefix("http://").split("/")[0])
    candidate, counter = base, 1
    existing = {c.id for c in configs}
    while candidate in existing:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def main() -> None:
    import uvicorn

    uvicorn.run("price_tracker.web:create_app", factory=True, host="127.0.0.1", port=8030)


if __name__ == "__main__":
    main()
