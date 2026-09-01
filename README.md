# Price Tracker — V2

Bot de suivi de prix en **un seul moteur, trois niveaux** (Automatique,
Personnalisé, Expert). Vous collez un lien : le moteur teste réellement
l'extraction, affiche sa confiance, puis enregistre. Historique versionné dans
le repo, alertes Discord/email, et une interface web FastAPI.

La V2 remplace l'ancien « scraping CSS » par le pipeline décrit dans
`proposition-price-tracker.md` :

```
ProductIntent → Resolver → TrackingConfig → Tracking Engine
                                            → Scraping Engine (JSON-LD / CSS /
                                              XPath / Regex / navigateur)
                                            → Validator → Historique
                                            → Alert Engine (Discord, email)
```

## Niveaux

- **🪄 Automatique** — une URL suffit. Le moteur détecte le prix (JSON-LD →
  OpenGraph → sélecteurs courants → regex), choisit le meilleur et re-détecte à
  chaque relevé (`strategy: auto`).
- **🎯 Personnalisé** — prix cible, fréquence, validation min/max ; la
  stratégie gagnante est verrouillée.
- **🛠️ Expert** — stratégie, sélecteur CSS, XPath, regex ou navigateur
  (Playwright) explicitement choisis, avec le panneau Playground pour tester
  avant d'enregistrer.

Le document `docs/ux-ajouter-produit.md` décrit l'expérience exacte de l'écran
« Ajouter un produit ».

## Utilisation

```bash
python -m venv .venv
source .venv/bin/activate            # .venv\Scripts\Activate.ps1 sous Windows
pip install -e ".[dev,web]"          # web option considéré hors navigateur

python -m price_tracker run          # scrape, met à jour l'historique, notifie
python -m price_tracker run --dry-run

# Ajouter par intention (teste réellement avant d'écrire)
python -m price_tracker add "https://boutique.example/produit" --name "Mon produit" \
       --target 800 --level custom --dry-run

# Playground : tester une extraction sans rien écrire
python -m price_tracker test "https://boutique.example/produit" --strategy jsonld

# Interface web
python -m price_tracker.web          # http://127.0.0.1:8030
```

`products.yaml` (format V2, rétro-compatible v1) reste modifiable à la main,
avec l'UI ou le CLI.

## Extraction

| Stratégie | Comment ça marche | Quand l'utiliser |
| --- | --- | --- |
| `jsonld` | Blocs `<script type="application/ld+json">` (Product/Offer/aggreggate) | Sites structurés (Schema.org) |
| `css` | Sélecteur CSS fourni | Sites classiques |
| `xpath` | Expression XPath (via `lxml`) | Sélecteurs complexes |
| `regex` | Expression régulière sur le HTML | Dernier recours, confiance faible |
| `browser` | Playwright (rendu JS) avant extraction | Prix chargé en JavaScript |

La détection automatique essaie `jsonld` → OpenGraph → sélecteurs courants →
`regex`, pondère chaque candidat et le Playground laisse voir et choisir.

**Navigateur (Playwright)** : extra optionnel, jamais lancé silencieusement —
son usage est explicite dans une configuration :

```bash
pip install -e ".[browser]"
playwright install chromium
```

## Notifications

Discord (webhook) et email (SMTP), toutes deux optionnelles : elles s'activent
dès qu'un secret existant est configuré dans l'environnement du cron GitHub
Actions (`DISCORD_WEBHOOK_URL`, `SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`, …).
Absentes, elles ne bloquent jamais un run.

## Web (interface FastAPI)

- `/` — tableau de bord : derniers relevés, variation, tendance, badge
  stratégie (niveau Expert uniquement) ;
- `/ajouter` — écran « Ajouter un produit » : résolution, confiance, choix du
  candidat, Playground ;
- `/api/resolve` — intention → configuration testée ; `/api/extract` —
  Playground ; `/api/products` — CRUD sur `products.yaml`.

**Pages légales** : `/mentions-legales`, `/confidentialite` (RGPD), `/contact`
et la 404 — les champs `[À compléter]` et `contact@exemple.fr` sont à
personnaliser avant mise en production.

**Identité visuelle** : papier crème (`--paper`), Georgia serif pour la
lecture, mono pour les relevés ; toutes les couleurs déclarées comme variables
dans `:root` (aucun hex/rgba ailleurs), pas de grille ni dégradé décoratif,
aucune Google Font, aucun build.

## Déploiement

1. Poussez sur GitHub — `track-prices.yml` relève les prix toutes les 6 h
   (cron modifiable) et commite l'historique ; le workflow est idempotent.
2. Interface web — serveur uvicorn (ou Docker) :

```bash
docker build -t price-tracker .
docker run -p 8030:8030 price-tracker
# compose un secret SMTP/Discord via variables d'environnement/GitHub secrets
```

Pour GitHub Pages, le dashboard statique dans `docs/` reste disponible.

## Tests

```bash
pip install -e ".[dev,web]"
ruff check .
ruff format --check .
pytest
```

Les tests sont hors-réseau : le moteur d'extraction est exercé sur des
fragments HTML représentatifs, et les appels extérieurs (HTTP/Playwright) sont
injectés. CI : `.github/workflows/ci.yml`.

## Stack

Python 3.11+, `requests` + `BeautifulSoup4` (+ `lxml` pour XPath), `PyYAML`,
FastAPI + uvicorn, HTML/CSS/JS vanilla (interface dans `web/`), Playwright
(extra optionnel), GitHub Actions (cron + CI).

## Usage responsable

Vérifiez le `robots.txt` et les conditions d'utilisation du site avant de
l'ajouter, et n'augmentez pas trop la fréquence du cron : ce projet est pensé
pour un usage personnel, respectueux des sites suivis. Les notifications sont
des effets externes — jamais de webhook ni mot de passe versionné.