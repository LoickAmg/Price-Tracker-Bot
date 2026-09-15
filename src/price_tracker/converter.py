"""Convertisseur de devise en temps réel.

Utilise l'API gratuite open.er-api.com (pas de clé requise).
Cache les taux en mémoire pendant 1 hour. Fallback sur des taux fixes
si l'API est indisponible.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation

import requests

logger = logging.getLogger(__name__)

_API_URL = "https://open.er-api.com/v6/latest/{base}"
_CACHE_TTL_SECONDS = 3600  # 1 hour

# Taux fixes de secours (approximatifs, mi-2025)
_FALLBACK_RATES: dict[str, dict[str, float]] = {
    "EUR": {
        "USD": 1.08,
        "GBP": 0.86,
        "CHF": 0.97,
        "CAD": 1.47,
        "JPY": 163.50,
        "CNY": 7.85,
        "XOF": 655.96,
        "XAF": 655.96,
        "NGN": 1650.0,
        "KES": 140.0,
        "ZAR": 21.50,
        "BRL": 5.30,
        "INR": 97.50,
        "KRW": 1480.0,
        "MXN": 18.50,
        "PLN": 4.30,
        "SEK": 11.40,
        "NOK": 11.60,
        "DKK": 7.46,
        "TRY": 35.00,
        "RUB": 98.00,
        "THB": 38.50,
        "MYR": 5.10,
        "SGD": 1.46,
        "HKD": 8.45,
        "TWD": 35.00,
        "PHP": 61.00,
        "IDR": 1700.0,
        "VND": 27500.0,
        "EGP": 52.00,
        "MAD": 10.80,
        "TND": 3.40,
        "DZD": 147.0,
        "GHS": 16.50,
        "TZS": 2700.0,
        "UGX": 4050.0,
        "ETB": 125.0,
        "COP": 4350.0,
        "PEN": 4.10,
        "CLP": 1000.0,
        "ARS": 1050.0,
        "CZK": 25.00,
        "HUF": 400.0,
        "RON": 4.97,
        "BGN": 1.96,
        "HRK": 7.46,
        "ISK": 150.0,
        "PHP": 61.00,
    },
    "USD": {
        "EUR": 0.93,
        "GBP": 0.79,
        "CHF": 0.90,
        "CAD": 1.36,
        "JPY": 151.50,
        "CNY": 7.28,
        "XOF": 608.00,
        "XAF": 608.00,
        "NGN": 1530.0,
        "KES": 130.0,
        "ZAR": 20.00,
        "BRL": 4.90,
        "INR": 90.00,
        "KRW": 1370.0,
        "MXN": 17.10,
        "PLN": 3.98,
        "SEK": 10.55,
        "NOK": 10.75,
        "DKK": 6.90,
        "TRY": 32.40,
        "RUB": 90.70,
        "THB": 35.60,
        "MYR": 4.72,
        "SGD": 1.35,
        "HKD": 7.82,
        "TWD": 32.40,
        "PHP": 56.50,
        "IDR": 15750.0,
        "VND": 25500.0,
        "EGP": 48.10,
        "MAD": 10.00,
        "TND": 3.15,
        "DZD": 136.0,
        "GHS": 15.30,
        "TZS": 2500.0,
        "UGX": 3750.0,
        "ETB": 116.0,
        "COP": 4030.0,
        "PEN": 3.80,
        "CLP": 925.0,
        "ARS": 970.0,
        "CZK": 23.15,
        "HUF": 370.0,
        "RON": 4.60,
        "BGN": 1.81,
        "HRK": 6.90,
        "ISK": 139.0,
        "PHP": 56.50,
    },
}


class CurrencyConverter:
    """Service de conversion de devise avec cache."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Decimal]] = {}
        self._cache_time: dict[str, float] = {}

    def _is_cache_valid(self, base: str) -> bool:
        if base not in self._cache_time:
            return False
        return (time.time() - self._cache_time[base]) < _CACHE_TTL_SECONDS

    def _fetch_rates(self, base: str) -> dict[str, Decimal]:
        """Récupère les taux depuis l'API ou le fallback."""
        if self._is_cache_valid(base):
            return self._cache[base]

        try:
            response = requests.get(
                _API_URL.format(base=base),
                timeout=10,
                headers={"User-Agent": "price-tracker-bot/0.2"},
            )
            response.raise_for_status()
            data = response.json()
            raw_rates = data.get("rates", {})
            rates = {}
            for code, value in raw_rates.items():
                try:
                    rates[code] = Decimal(str(value))
                except (InvalidOperation, ValueError):
                    continue
            self._cache[base] = rates
            self._cache_time[base] = time.time()
            logger.info("Taux de change chargés pour %s (%d devises)", base, len(rates))
            return rates
        except Exception as exc:
            logger.warning("API taux indisponible pour %s, fallback : %s", base, exc)
            # Fallback sur les taux fixes
            fallback = _FALLBACK_RATES.get(base, {})
            rates = {code: Decimal(str(val)) for code, val in fallback.items()}
            rates[base] = Decimal("1")
            self._cache[base] = rates
            self._cache_time[base] = time.time()
            return rates

    def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Decimal | None:
        """Convertit un montant d'une devise à une autre.

        Renvoie None si la conversion est impossible.
        """
        from_currency = from_currency.upper().strip()
        to_currency = to_currency.upper().strip()

        if from_currency == to_currency:
            return amount

        rates = self._fetch_rates(from_currency)
        rate = rates.get(to_currency)
        if rate is None:
            logger.warning("Taux introuvable : %s → %s", from_currency, to_currency)
            return None

        return (amount * rate).quantize(Decimal("0.01"))

    def get_rate(self, from_currency: str, to_currency: str) -> Decimal | None:
        """Renvoie le taux de conversion (1 unité)."""
        result = self.convert(Decimal("1"), from_currency, to_currency)
        return result


# Instance singleton
_converter: CurrencyConverter | None = None


def get_converter() -> CurrencyConverter:
    global _converter
    if _converter is None:
        _converter = CurrencyConverter()
    return _converter


# Devises supportées (code → nom)
SUPPORTED_CURRENCIES: dict[str, str] = {
    "EUR": "Euro",
    "USD": "Dollar américain",
    "GBP": "Livre sterling",
    "CHF": "Franc suisse",
    "CAD": "Dollar canadien",
    "JPY": "Yen japonais",
    "CNY": "Yuan chinois",
    "XOF": "Franc CFA (UEMOA)",
    "XAF": "Franc CFA (CEMAC)",
    "NGN": "Naira nigérian",
    "KES": "Shilling kényan",
    "ZAR": "Rand sud-africain",
    "BRL": "Réal brésilien",
    "INR": "Roupie indienne",
    "KRW": "Won sud-coréen",
    "MXN": "Peso mexicain",
    "PLN": "Zloty polonais",
    "SEK": "Couronne suédoise",
    "NOK": "Couronne norvégienne",
    "DKK": "Couronne danoise",
    "TRY": "Lire turque",
    "RUB": "Rouble russe",
    "THB": "Baht thaïlandais",
    "MYR": "Ringgit malais",
    "SGD": "Dollar de Singapour",
    "HKD": "Dollar de Hong Kong",
    "TWD": "Dollar taïwanais",
    "PHP": "Peso philippin",
    "IDR": "Rupiah indonésien",
    "VND": "Dong vietnamien",
    "EGP": "Livre égyptienne",
    "MAD": "Dirham marocain",
    "TND": "Dinar tunisien",
    "DZD": "Dinar algérien",
    "GHS": "Cedi ghanéen",
    "TZS": "Shilling tanzanien",
    "UGX": "Shilling ougandais",
    "ETB": "Birr éthiopien",
    "COP": "Peso colombien",
    "PEN": "Sol péruvien",
    "CLP": "Peso chilien",
    "ARS": "Peso argentin",
    "CZK": "Couronne tchèque",
    "HUF": "Forint hongrois",
    "RON": "Leu roumain",
    "BGN": "Lev bulgare",
    "ISK": "Couronne islandaise",
}
